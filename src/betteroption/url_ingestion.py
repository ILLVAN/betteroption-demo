"""Conservative public-URL ingestion for job advertisements."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import unicodedata
import warnings
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, XMLParsedAsHTMLWarning
from pydantic import Field

from .profile import StrictModel


USER_AGENT = "BetterOption/0.7.2k"
SUPPORTED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/ld+json",
}


class UrlFailureKind(StrEnum):
    EXPIRED = "expired"
    UNREACHABLE = "unreachable"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class UrlIngestionError(RuntimeError):
    """Raised when a URL cannot be fetched safely or converted to useful text."""

    def __init__(
        self,
        message: str,
        *,
        kind: UrlFailureKind = UrlFailureKind.UNREACHABLE,
        http_status: int | None = None,
    ) -> None:
        self.kind = kind
        self.http_status = http_status
        super().__init__(message)


class FetchedDocument(StrictModel):
    requested_url: str
    final_url: str
    status_code: int = Field(ge=200, lt=300)
    content_type: str
    text: str = Field(min_length=1, max_length=150_000)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


UNAVAILABLE_PAGE_MARKERS = (
    "job is no longer available",
    "position is no longer available",
    "position has been filled",
    "this job has expired",
    "job posting has expired",
    "job not found",
    "vacancy is no longer available",
    "no longer accepting applications",
    "applications are closed",
    "application period has ended",
    "this vacancy has expired",
    "this vacancy is closed",
    "stellenanzeige ist abgelaufen",
    "stelle ist nicht mehr verfügbar",
    "bewerbungsfrist ist abgelaufen",
)


def _default_resolver(host: str) -> list[str]:
    return list(
        {address[4][0] for address in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    )


def _job_posting_objects(value: object) -> Iterable[dict]:
    if isinstance(value, list):
        for item in value:
            yield from _job_posting_objects(item)
    elif isinstance(value, dict):
        raw_type = value.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(item).casefold() == "jobposting" for item in types):
            yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from _job_posting_objects(item)


def _plain_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(filter(None, (_plain_text(item) for item in value)))
    if isinstance(value, dict):
        preferred = value.get("name") or value.get("value") or value.get("address")
        return _plain_text(preferred or list(value.values()))
    material = str(value)
    # Schema.org descriptions are HTML fragments even when an employer embeds
    # XML-looking markup inside them. Treat them as fragments deliberately and
    # silence only BeautifulSoup's whole-document heuristic for this one parse.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        warnings.simplefilter("ignore", MarkupResemblesLocatorWarning)
        return BeautifulSoup(material, "html.parser").get_text(" ", strip=True)


def _normalized_job_identity_text(value: object) -> str:
    """Normalize exact structured identity fields without fuzzy matching."""

    return " ".join(unicodedata.normalize("NFKC", _plain_text(value)).casefold().split())


def _job_posting_identity(posting: dict) -> tuple[str, ...]:
    """Return a conservative identity for repeated JobPosting renderings."""

    for field in ("@id", "url"):
        explicit = posting.get(field)
        if isinstance(explicit, str) and (normalized := explicit.strip()):
            return ("explicit", normalized)

    fallback = (
        _normalized_job_identity_text(posting.get("title")),
        _normalized_job_identity_text(posting.get("hiringOrganization")),
        _normalized_job_identity_text(posting.get("jobLocation")),
    )
    if any(fallback):
        return ("fields", *fallback)

    # Malformed JobPosting objects without even the fallback identity fields
    # must not all collapse into one apparent vacancy. Exact JSON equality can
    # still identify a duplicated rendering without guessing.
    return (
        "object",
        json.dumps(posting, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _html_job_postings(content: str) -> list[dict]:
    soup = BeautifulSoup(content, "html.parser")
    postings: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        postings.extend(_job_posting_objects(data))
    return postings


def _unique_job_postings(postings: Iterable[dict]) -> list[dict]:
    unique: dict[tuple[str, ...], dict] = {}
    for posting in postings:
        unique.setdefault(_job_posting_identity(posting), posting)
    return list(unique.values())


def _unique_html_job_postings(content: str) -> list[dict]:
    return _unique_job_postings(_html_job_postings(content))


def _unique_json_ld_job_postings(content: str) -> list[dict]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    return _unique_job_postings(_job_posting_objects(data))


def extract_job_text(content: str, content_type: str) -> str:
    if content_type in {"text/plain", "application/ld+json"}:
        return content.strip()

    soup = BeautifulSoup(content, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for posting in _job_posting_objects(data):
            organization = posting.get("hiringOrganization")
            fields = (
                ("Title", posting.get("title")),
                ("Company", organization),
                ("Employer website", _organization_website(organization)),
                ("Location", posting.get("jobLocation")),
                ("Employment type", posting.get("employmentType")),
                ("Description", posting.get("description")),
                ("Responsibilities", posting.get("responsibilities")),
                ("Qualifications", posting.get("qualifications")),
                ("Skills", posting.get("skills")),
                ("Salary", posting.get("baseSalary")),
                ("Date posted", posting.get("datePosted")),
                ("Valid through", posting.get("validThrough")),
            )
            text = "\n".join(
                f"{label}: {plain}" for label, value in fields if (plain := _plain_text(value))
            )
            if len(text) >= 80:
                return text

    for element in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
        element.decompose()
    container = soup.find("main") or soup.find("article") or soup.body or soup
    return "\n".join(container.stripped_strings)


def _organization_website(value: object) -> str:
    """Keep an employer-controlled URL from JobPosting JSON-LD when supplied."""

    if not isinstance(value, dict):
        return ""
    candidates = [value.get("sameAs"), value.get("url")]
    for candidate in candidates:
        values = candidate if isinstance(candidate, list) else [candidate]
        for item in values:
            url = str(item or "").strip()
            parsed = urlsplit(url)
            if parsed.scheme in {"http", "https"} and parsed.hostname:
                return url
    return ""


def _looks_unavailable(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    if any(marker in normalized for marker in UNAVAILABLE_PAGE_MARKERS):
        return True
    # Search-index landing pages sometimes keep the complete advertisement and
    # return HTTP 200 after closing it. Their visible status badge commonly uses
    # wording such as “Expired 27d ago”, which can sit outside JobPosting JSON-LD.
    return bool(
        re.search(
            r"\bexpired\s+(?:about\s+)?\d+\s*(?:d|day|days|h|hour|hours|week|weeks|month|months)\s+ago\b",
            normalized,
        )
    )


def _visible_page_text(content: str, content_type: str) -> str:
    """Return human-visible status text without trusting structured job data alone."""

    if content_type != "text/html" and content_type != "application/xhtml+xml":
        return content
    soup = BeautifulSoup(content, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    return " ".join(soup.stripped_strings)


def save_fetched_document(
    document: FetchedDocument,
    directory: Path = Path("local-data") / "source-snapshots",
) -> Path:
    """Persist the fetched source before any LLM call for reproducible debugging."""

    directory.mkdir(parents=True, exist_ok=True)
    identity = sha256(f"{document.final_url}\0{document.text}".encode("utf-8")).hexdigest()[:20]
    path = directory / f"source-snapshot-{identity}.json"
    path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    return path


class PublicUrlFetcher:
    """Fetch only public HTTP(S) pages while honoring robots and size limits."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] = _default_resolver,
        maximum_bytes: int = 2_000_000,
        maximum_redirects: int = 5,
    ) -> None:
        self.client = client or httpx.Client(
            follow_redirects=False,
            timeout=15.0,
            trust_env=False,
        )
        self.resolver = resolver
        self.maximum_bytes = maximum_bytes
        self.maximum_redirects = maximum_redirects

    def _validate_public_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise UrlIngestionError(
                "only http and https URLs are supported",
                kind=UrlFailureKind.INVALID,
            )
        if not parsed.hostname or parsed.username or parsed.password:
            raise UrlIngestionError(
                "URL must contain a public host and no credentials",
                kind=UrlFailureKind.INVALID,
            )
        try:
            addresses = self.resolver(parsed.hostname)
        except OSError as exc:
            raise UrlIngestionError(
                f"could not resolve URL host: {parsed.hostname}",
                kind=UrlFailureKind.UNREACHABLE,
            ) from exc
        if not addresses:
            raise UrlIngestionError(
                f"URL host resolved to no address: {parsed.hostname}",
                kind=UrlFailureKind.UNREACHABLE,
            )
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise UrlIngestionError(
                    "URL host resolved to an invalid IP address",
                    kind=UrlFailureKind.INVALID,
                ) from exc
            if not ip.is_global:
                raise UrlIngestionError(
                    "private, local, and reserved network targets are blocked",
                    kind=UrlFailureKind.BLOCKED,
                )

    def _check_robots(self, url: str) -> None:
        parsed = urlsplit(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = self.client.get(
                robots_url,
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
            )
        except httpx.HTTPError:
            return
        if response.status_code in {401, 403}:
            raise UrlIngestionError(
                "the site does not permit automated access",
                kind=UrlFailureKind.BLOCKED,
                http_status=response.status_code,
            )
        if response.status_code != 200:
            return
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        if not parser.can_fetch(USER_AGENT, url):
            raise UrlIngestionError(
                "robots.txt does not permit fetching this URL",
                kind=UrlFailureKind.BLOCKED,
            )

    def fetch(self, url: str) -> FetchedDocument:
        requested_url = url.strip()
        current_url = requested_url
        for redirect_count in range(self.maximum_redirects + 1):
            self._validate_public_url(current_url)
            self._check_robots(current_url)
            try:
                with self.client.stream(
                    "GET",
                    current_url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml,text/plain",
                    },
                    timeout=20.0,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise UrlIngestionError("redirect response has no destination")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    content_type = content_type.strip().lower()
                    if content_type not in SUPPORTED_CONTENT_TYPES:
                        raise UrlIngestionError(
                            f"unsupported response content type: {content_type or 'unknown'}",
                            kind=UrlFailureKind.UNSUPPORTED,
                            http_status=response.status_code,
                        )
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.maximum_bytes:
                            raise UrlIngestionError(
                                "job page exceeds the download size limit",
                                kind=UrlFailureKind.UNSUPPORTED,
                                http_status=response.status_code,
                            )
                        chunks.append(chunk)
                    encoding = response.encoding or "utf-8"
                    content = b"".join(chunks).decode(encoding, errors="replace")
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                raise UrlIngestionError(
                    f"job page returned HTTP {status_code}",
                    kind=(
                        UrlFailureKind.EXPIRED
                        if status_code in {404, 410}
                        else UrlFailureKind.UNREACHABLE
                    ),
                    http_status=status_code,
                ) from exc
            except httpx.HTTPError as exc:
                raise UrlIngestionError(
                    "job page could not be downloaded",
                    kind=UrlFailureKind.UNREACHABLE,
                ) from exc

            unique_postings = (
                _unique_html_job_postings(content)
                if content_type in {"text/html", "application/xhtml+xml"}
                else (
                    _unique_json_ld_job_postings(content)
                    if content_type == "application/ld+json"
                    else []
                )
            )
            if len(unique_postings) > 1:
                raise UrlIngestionError(
                    "the URL contains multiple distinct job postings; open an individual "
                    "vacancy page or paste one job description manually",
                    kind=UrlFailureKind.UNSUPPORTED,
                    http_status=response.status_code,
                )
            # Check the visible page before extracting a unique JSON-LD job. A
            # closed badge can live outside otherwise valid, stale structured data.
            if _looks_unavailable(_visible_page_text(content, content_type)):
                raise UrlIngestionError(
                    "the job URL appears to be expired or unavailable",
                    kind=UrlFailureKind.EXPIRED,
                    http_status=response.status_code,
                )
            text = extract_job_text(content, content_type).strip()
            if len(text) < 80:
                raise UrlIngestionError(
                    "the URL did not expose enough job text; this source is not currently supported",
                    kind=UrlFailureKind.UNSUPPORTED,
                    http_status=response.status_code,
                )
            if _looks_unavailable(text):
                raise UrlIngestionError(
                    "the job URL appears to be expired or unavailable",
                    kind=UrlFailureKind.EXPIRED,
                    http_status=response.status_code,
                )
            return FetchedDocument(
                requested_url=requested_url,
                final_url=current_url,
                status_code=response.status_code,
                content_type=content_type,
                text=text[:150_000],
            )

        raise UrlIngestionError("job page exceeded the redirect limit")
