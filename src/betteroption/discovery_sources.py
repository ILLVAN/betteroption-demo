"""Public ATS connectors and the bounded discovery source mesh."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, wait
from contextvars import copy_context
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlsplit

import httpx

from .brave_search import BraveSearchError
from .concurrency import DaemonThreadPoolExecutor, cooperative_control
from .discovery import (
    DiscoveryAvailabilityFilter,
    DiscoveredJob,
    DiscoveryAttribution,
    DiscoveryError,
    DiscoveryQuery,
    JobDiscoveryProvider,
    WEB_DISCOVERY_EXCLUDED_DOMAINS,
    _PLACE_INDEX,
    _raw_web_only,
    _market_safe_web_location,
    _portal_search_texts,
    _regional_search_locations,
    _remote_only_signal,
    _tokens,
    _web_search_texts,
    discovered_job_has_structured_role_evidence,
    finalize_discovered_jobs,
    web_discovery_matches_portal,
    web_discovery_result_is_plausible_job,
    web_discovery_url_is_error_landing,
)
from .geography import OfflinePlaceIndex
from .provider_permissions import provider_permission_allowed


class ConfiguredAtsBoard:
    """One explicitly configured public company job board."""

    def __init__(self, company: str, token: str, *, region: str = "global") -> None:
        clean_company = " ".join(company.split())
        clean_token = token.strip().strip("/")
        if not clean_company or not re.fullmatch(r"[A-Za-z0-9_-]+", clean_token):
            raise ValueError("ATS boards require Company=board-token entries")
        if region not in {"global", "eu"}:
            raise ValueError("ATS board region must be global or eu")
        self.company = clean_company
        self.token = clean_token
        self.region = region

    @property
    def identity(self) -> tuple[str, str]:
        return self.region, self.token.casefold()


def parse_configured_boards(
    value: str, *, allow_eu_prefix: bool = False
) -> list[ConfiguredAtsBoard]:
    """Parse ``Company=token; Other Company=token`` without hidden guessing."""

    boards: list[ConfiguredAtsBoard] = []
    for item in value.split(";"):
        clean = item.strip()
        if not clean:
            continue
        if "=" not in clean:
            raise ValueError("ATS board configuration must use Company=board-token")
        company, token = clean.split("=", 1)
        region = "global"
        if allow_eu_prefix and token.casefold().startswith("eu:"):
            token = token[3:]
            region = "eu"
        board = ConfiguredAtsBoard(company, token, region=region)
        if board.identity not in {existing.identity for existing in boards}:
            boards.append(board)
    return boards


class GreenhouseDiscoveryProvider:
    """Read published jobs from Greenhouse's documented public Job Board API."""

    name = "greenhouse"
    attribution = "Published jobs via Greenhouse Job Board API"
    attribution_url = "https://developers.greenhouse.io/job-board.html"

    def __init__(
        self,
        boards: Iterable[ConfiguredAtsBoard],
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.boards = _unique_boards(boards)
        self.client = client or _json_client(timeout_seconds)

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        jobs: list[DiscoveredJob] = []
        successful = 0
        errors: list[str] = []
        for board in self.boards:
            try:
                response = self.client.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{board.token}/jobs",
                    params={"content": "true"},
                )
                response.raise_for_status()
                rows = response.json().get("jobs", [])
                if not isinstance(rows, list):
                    raise ValueError("Greenhouse response did not contain jobs")
                successful += 1
                jobs.extend(self._parse(board, row) for row in rows if isinstance(row, dict))
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                errors.append(f"{board.company}: {type(exc).__name__}")
        if not successful and errors:
            raise DiscoveryError(f"Greenhouse boards were unavailable ({'; '.join(errors)}).")
        return _relevant_jobs(query, jobs)

    @staticmethod
    def _parse(board: ConfiguredAtsBoard, row: dict[str, object]) -> DiscoveredJob:
        location = row.get("location")
        location_name = (
            str(location.get("name") or "Location not stated")
            if isinstance(location, dict)
            else "Location not stated"
        )
        departments = row.get("departments") or []
        offices = row.get("offices") or []
        tags = [
            str(item.get("name") or "").strip()
            for item in [
                *(departments if isinstance(departments, list) else []),
                *(offices if isinstance(offices, list) else []),
            ]
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        job_id = str(row.get("id") or "").strip()
        source_url = str(row.get("absolute_url") or "").strip()
        if not source_url and job_id:
            source_url = f"https://job-boards.greenhouse.io/{board.token}/jobs/{job_id}"
        if not job_id or not source_url:
            raise ValueError("Greenhouse job did not contain an id and source URL")
        summary = _plain_text(str(row.get("content") or ""))
        company = str(row.get("company_name") or board.company).strip()
        return DiscoveredJob(
            provider="greenhouse",
            external_id=f"{board.token}:{job_id}",
            title=str(row.get("title") or "Untitled role").strip(),
            company=company,
            location=location_name,
            remote="remote" in location_name.casefold(),
            tags=tags[:12],
            summary=summary[:1_500],
            source_url=source_url,
            published_at=_parse_datetime(row.get("first_published")),
        )


class LeverDiscoveryProvider:
    """Read public, published jobs through Lever's official Postings API."""

    name = "lever"
    attribution = "Published jobs via Lever Postings API"
    attribution_url = "https://github.com/lever/postings-api"

    def __init__(
        self,
        boards: Iterable[ConfiguredAtsBoard],
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.boards = _unique_boards(boards)
        self.client = client or _json_client(timeout_seconds)

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        jobs: list[DiscoveredJob] = []
        successful = 0
        errors: list[str] = []
        for board in self.boards:
            host = "api.eu.lever.co" if board.region == "eu" else "api.lever.co"
            try:
                response = self.client.get(
                    f"https://{host}/v0/postings/{board.token}",
                    params={"mode": "json", "limit": 100},
                )
                response.raise_for_status()
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError("Lever response was not a job list")
                successful += 1
                jobs.extend(self._parse(board, row) for row in rows if isinstance(row, dict))
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                errors.append(f"{board.company}: {type(exc).__name__}")
        if not successful and errors:
            raise DiscoveryError(f"Lever boards were unavailable ({'; '.join(errors)}).")
        return _relevant_jobs(query, jobs)

    @staticmethod
    def _parse(board: ConfiguredAtsBoard, row: dict[str, object]) -> DiscoveredJob:
        categories = row.get("categories")
        categories = categories if isinstance(categories, dict) else {}
        location = str(categories.get("location") or "Location not stated").strip()
        tags = [
            str(categories.get(key) or "").strip()
            for key in ("team", "department", "commitment")
            if str(categories.get(key) or "").strip()
        ]
        job_id = str(row.get("id") or "").strip()
        source_url = str(row.get("hostedUrl") or row.get("applyUrl") or "").strip()
        if not job_id or not source_url:
            raise ValueError("Lever job did not contain an id and hosted URL")
        material = " ".join((location, str(row.get("workplaceType") or ""))).casefold()
        description = " ".join(
            str(row.get(key) or "")
            for key in ("descriptionPlain", "additionalPlain", "description")
        )
        return DiscoveredJob(
            provider="lever",
            external_id=f"{board.token}:{job_id}",
            title=str(row.get("text") or "Untitled role").strip(),
            company=board.company,
            location=location,
            remote="remote" in material,
            tags=tags[:12],
            summary=_plain_text(description)[:1_500],
            source_url=source_url,
            published_at=_parse_epoch_milliseconds(row.get("createdAt")),
        )


class AshbyDiscoveryProvider:
    """Read listed jobs from Ashby's documented public Job Postings API."""

    name = "ashby"
    attribution = "Published jobs via Ashby Job Postings API"
    attribution_url = "https://developers.ashbyhq.com/docs/public-job-posting-api"

    def __init__(
        self,
        boards: Iterable[ConfiguredAtsBoard],
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.boards = _unique_boards(boards)
        self.client = client or _json_client(timeout_seconds)

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        jobs: list[DiscoveredJob] = []
        successful = 0
        errors: list[str] = []
        for board in self.boards:
            try:
                response = self.client.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{board.token}",
                    params={"includeCompensation": "true"},
                )
                response.raise_for_status()
                rows = response.json().get("jobs", [])
                if not isinstance(rows, list):
                    raise ValueError("Ashby response did not contain jobs")
                successful += 1
                jobs.extend(
                    self._parse(board, row)
                    for row in rows
                    if isinstance(row, dict) and row.get("isListed", True)
                )
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                errors.append(f"{board.company}: {type(exc).__name__}")
        if not successful and errors:
            raise DiscoveryError(f"Ashby boards were unavailable ({'; '.join(errors)}).")
        return _relevant_jobs(query, jobs)

    @staticmethod
    def _parse(board: ConfiguredAtsBoard, row: dict[str, object]) -> DiscoveredJob:
        source_url = str(row.get("jobUrl") or row.get("applyUrl") or "").strip()
        job_id = str(row.get("id") or source_url).strip()
        if not source_url:
            raise ValueError("Ashby job did not contain a job URL")
        location = str(row.get("location") or "Location not stated").strip()
        workplace = str(row.get("workplaceType") or "").strip()
        tags = [
            str(row.get(key) or "").strip()
            for key in ("department", "team", "employmentType", "workplaceType")
            if str(row.get(key) or "").strip()
        ]
        return DiscoveredJob(
            provider="ashby",
            external_id=f"{board.token}:{job_id}",
            title=str(row.get("title") or "Untitled role").strip(),
            company=board.company,
            location=location,
            remote=bool(row.get("isRemote")) or workplace.casefold() == "remote",
            tags=tags[:12],
            summary=_plain_text(
                str(row.get("descriptionPlain") or row.get("descriptionHtml") or "")
            )[:1_500],
            source_url=source_url,
            published_at=_parse_datetime(row.get("publishedAt")),
        )


class AtsDiscoveryExpander:
    """Expand configured and search-discovered ATS boards through public APIs."""

    attributions = [
        DiscoveryAttribution(
            label=GreenhouseDiscoveryProvider.attribution,
            url=GreenhouseDiscoveryProvider.attribution_url,
        ),
        DiscoveryAttribution(
            label=LeverDiscoveryProvider.attribution,
            url=LeverDiscoveryProvider.attribution_url,
        ),
        DiscoveryAttribution(
            label=AshbyDiscoveryProvider.attribution,
            url=AshbyDiscoveryProvider.attribution_url,
        ),
    ]

    def __init__(
        self,
        *,
        greenhouse_boards: Iterable[ConfiguredAtsBoard] = (),
        lever_boards: Iterable[ConfiguredAtsBoard] = (),
        ashby_boards: Iterable[ConfiguredAtsBoard] = (),
        max_discovered_boards: int = 12,
        client: httpx.Client | None = None,
    ) -> None:
        self.greenhouse_boards = list(greenhouse_boards)
        self.lever_boards = list(lever_boards)
        self.ashby_boards = list(ashby_boards)
        self.max_discovered_boards = max(0, min(30, max_discovered_boards))
        self.client = client

    def search(
        self,
        query: DiscoveryQuery,
        seeds: Iterable[DiscoveredJob],
        *,
        timeout_seconds: float = 20.0,
        check_control: Callable[[], None] | None = None,
    ) -> list[DiscoveredJob]:
        if not provider_permission_allowed("ats"):
            return []
        detected = self._detected_boards(seeds)
        groups = (
            (
                GreenhouseDiscoveryProvider,
                [*self.greenhouse_boards, *detected["greenhouse"]],
            ),
            (LeverDiscoveryProvider, [*self.lever_boards, *detected["lever"]]),
            (AshbyDiscoveryProvider, [*self.ashby_boards, *detected["ashby"]]),
        )
        jobs: list[DiscoveredJob] = []
        requests: list[tuple[type, list[ConfiguredAtsBoard]]] = []
        for provider_type, boards in groups:
            unique = _unique_boards(boards)
            if unique:
                requests.append((provider_type, unique))
        if not requests:
            return jobs

        executor = DaemonThreadPoolExecutor(
            max_workers=len(requests),
            thread_name_prefix="ats-discovery",
        )
        futures = [
            executor.submit(provider_type(boards, client=self.client).search, query)
            for provider_type, boards in requests
        ]
        pending = set(futures)
        completed = set()
        deadline = time.monotonic() + max(0.0, min(20.0, timeout_seconds))
        try:
            while pending:
                if check_control is not None:
                    check_control()
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                batch, pending = wait(
                    pending,
                    timeout=min(0.25, remaining),
                    return_when=FIRST_COMPLETED,
                )
                completed.update(batch)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        for future in completed:
            try:
                jobs.extend(future.result())
            except DiscoveryError:
                continue
        return jobs

    def _detected_boards(
        self,
        seeds: Iterable[DiscoveredJob],
    ) -> dict[str, list[ConfiguredAtsBoard]]:
        result: dict[str, list[ConfiguredAtsBoard]] = {
            "greenhouse": [],
            "lever": [],
            "ashby": [],
        }
        for job in seeds:
            if sum(len(items) for items in result.values()) >= self.max_discovered_boards:
                break
            parsed = urlsplit(str(job.source_url))
            host = (parsed.hostname or "").casefold()
            parts = [part for part in parsed.path.split("/") if part]
            if not parts:
                continue
            try:
                if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
                    result["greenhouse"].append(ConfiguredAtsBoard(job.company, parts[0]))
                elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
                    region = "eu" if host == "jobs.eu.lever.co" else "global"
                    result["lever"].append(ConfiguredAtsBoard(job.company, parts[0], region=region))
                elif host == "jobs.ashbyhq.com":
                    result["ashby"].append(ConfiguredAtsBoard(job.company, parts[0]))
            except ValueError:
                continue
        return {name: _unique_boards(boards) for name, boards in result.items()}


class ExaFallbackDiscoveryProvider:
    """Focused semantic web discovery; legacy class and storage keys stay compatible."""

    name = "exa-fallback"
    attribution = "Exa Search"
    attribution_url = "https://exa.ai/docs/reference/search-api-guide-for-coding-agents"
    endpoint = "https://api.exa.ai/search"
    excluded_domains = sorted(WEB_DISCOVERY_EXCLUDED_DOMAINS)

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
        search_budget_seconds: float = 140.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Exa Search requires a non-empty API key")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key.strip(),
            "User-Agent": _user_agent(),
        }
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)
        self.search_budget_seconds = max(10.0, min(180.0, search_budget_seconds))
        self.last_request_count = 0

    @staticmethod
    def maximum_request_count(query: DiscoveryQuery) -> int:
        searches = [*_web_search_texts(query)[:12], *_portal_search_texts(query)]
        return max(1, len(searches))

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.last_request_count = 0
        regional_locations = _regional_search_locations(query)
        # Focused searches cover independent role/locality bundles rather than
        # one oversized keyword request. The source mesh compares the results
        # locally with every other configured provider.
        search_texts = [
            *_web_search_texts(query)[:12],
            *_portal_search_texts(query),
        ] or [
            " ".join(
                part
                for part in (
                    query.text.replace("·", " "),
                    query.location,
                    "open jobs careers",
                )
                if part
            )
        ]
        origin = _PLACE_INDEX.resolve(query.location)
        request_count = 0
        request_count_lock = Lock()

        def fetch(search_text: str) -> list[DiscoveredJob]:
            nonlocal request_count
            with request_count_lock:
                request_count += 1
            payload: dict[str, object] = {
                "query": search_text,
                "type": "fast",
                "numResults": min(40, query.limit),
                "excludeDomains": self.excluded_domains,
                "moderation": True,
                "contents": {"highlights": {"maxCharacters": 1_200}},
            }
            if origin is not None and not query.worldwide:
                payload["userLocation"] = origin.country_code
            response = self.client.post(
                self.endpoint,
                json=payload,
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
            if not isinstance(rows, list):
                raise ValueError("Exa response did not contain results")
            return [
                parsed
                for row in rows
                if self._usable(row)
                if (parsed := self._parse(row, query, regional_locations)) is not None
            ]

        jobs: list[DiscoveredJob] = []
        executor = DaemonThreadPoolExecutor(
            max_workers=min(4, len(search_texts)),
            thread_name_prefix="exa-search",
        )
        futures = [executor.submit(fetch, search_text) for search_text in search_texts]
        completed, pending = wait(futures, timeout=self.search_budget_seconds)
        errors = 0
        for future in completed:
            try:
                jobs.extend(future.result())
            except (httpx.HTTPError, TypeError, ValueError):
                errors += 1
        non_cancelled_futures = len(completed)
        for future in pending:
            if not future.cancel():
                non_cancelled_futures += 1
        executor.shutdown(wait=False, cancel_futures=True)
        with request_count_lock:
            # A non-cancellable timed-out future has consumed a provider call;
            # account for it even though this method returns before its result.
            self.last_request_count = max(request_count, non_cancelled_futures)
        if not jobs and errors == len(completed):
            raise DiscoveryError("Exa was unavailable for every focused search.")
        return _relevant_jobs(query, _deduplicate_jobs(jobs))

    @staticmethod
    def _usable(row: object) -> bool:
        if not isinstance(row, dict):
            return False
        value = str(row.get("url") or "").strip()
        highlights = row.get("highlights") or []
        summary = " ".join(
            str(item).strip()
            for item in (highlights if isinstance(highlights, list) else [])
            if str(item).strip()
        )
        return web_discovery_result_is_plausible_job(
            value,
            str(row.get("title") or ""),
            summary,
        )

    @staticmethod
    def _parse(
        row: dict[str, object],
        query: DiscoveryQuery,
        regional_locations: list[str],
    ) -> DiscoveredJob | None:
        url = str(row.get("url") or "").strip()
        if web_discovery_url_is_error_landing(url):
            return None
        highlights = row.get("highlights") or []
        summary = " ".join(
            str(item).strip()
            for item in (highlights if isinstance(highlights, list) else [])
            if str(item).strip()
        )
        company = (urlsplit(url).hostname or "Employer source").removeprefix("www.")
        title = _plain_text(str(row.get("title") or "Job opportunity"))[:500]
        material = f"{title} {summary}"
        remote = _remote_only_signal(material)
        location = _market_safe_web_location(
            title,
            summary,
            query,
            regional_locations,
            remote=remote,
            source_url=url,
        )
        if location is None:
            return None
        tags = ["Source verification required"]
        if web_discovery_matches_portal(url, query):
            tags.insert(0, "Saved employer portal")
        return DiscoveredJob(
            provider="exa-fallback",
            external_id=str(row.get("id") or url),
            title=title,
            company=company[:500],
            location=location,
            remote=remote,
            tags=tags,
            summary=_plain_text(summary)[:1_500],
            source_url=url,
            published_at=_parse_datetime(row.get("publishedDate")),
        )


def _you_web_rows(response: httpx.Response) -> list[dict[str, object]]:
    """Decode You Search results without assuming that useful text is HTML.

    The REST endpoint normally returns ``results.web`` as structured JSON.  Its
    optional live-crawl content is Markdown under ``contents.markdown``.  The
    platform console can also render a result collection as Markdown, so a
    successful Markdown response is accepted only when it contains explicit
    HTTP(S) links; every recovered row still passes the ordinary vacancy and
    source-validation gates later in the Explore workflow.
    """

    try:
        payload: object = response.json()
    except ValueError:
        rows = _you_markdown_rows(response.text)
        if rows:
            return rows
        raise ValueError("You.com response was neither Search JSON nor linked Markdown") from None

    if not isinstance(payload, dict):
        raise ValueError("You.com response was not a JSON object")
    results = payload.get("results")
    if isinstance(results, dict) and "web" in results:
        return _you_rows_value(results["web"])

    # Some first-party client/rendering surfaces unwrap ``results.web`` while
    # keeping the same result objects.  Supporting that representation is safe:
    # a response without an explicit web collection still fails closed.
    if "web" in payload:
        return _you_rows_value(payload["web"])
    for key in ("markdown", "content"):
        value = payload.get(key)
        if isinstance(value, str):
            rows = _you_markdown_rows(value)
            if rows:
                return rows
    raise ValueError("You.com response did not contain web results")


def _you_rows_value(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        if not all(isinstance(row, dict) for row in value):
            raise ValueError("You.com web results contained an invalid row")
        return [dict(row) for row in value]
    if isinstance(value, str):
        rows = _you_markdown_rows(value)
        if rows:
            return rows
    raise ValueError("You.com web results were not a list or linked Markdown")


def _you_markdown_rows(value: str) -> list[dict[str, object]]:
    """Recover linked result cards from a Markdown-rendered Search response."""

    clean = value.strip()
    if not clean:
        return []
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    link_pattern = re.compile(
        r"\[(?P<title>[^\]\n]{2,500})\]\((?P<url>https?://[^\s)>]+)\)",
        flags=re.IGNORECASE,
    )
    matches = list(link_pattern.finditer(clean))
    for index, match in enumerate(matches):
        url = match.group("url").rstrip(".,;:")
        identity = url.casefold().rstrip("/")
        if identity in seen:
            continue
        seen.add(identity)
        line_start = clean.rfind("\n", 0, match.start()) + 1
        next_result = matches[index + 1].start() if index + 1 < len(matches) else len(clean)
        context = clean[line_start : min(next_result, line_start + 1_500)]
        rows.append(
            {
                "url": url,
                "title": _markdown_plain_text(match.group("title")),
                "description": _markdown_plain_text(context),
            }
        )
    return rows


def _you_row_title(row: dict[str, object]) -> str:
    title = _markdown_plain_text(str(row.get("title") or ""))
    if title:
        return title
    contents = row.get("contents")
    markdown = contents.get("markdown") if isinstance(contents, dict) else None
    if isinstance(markdown, str):
        heading = re.search(r"^\s{0,3}#{1,6}\s+(.+)$", markdown, flags=re.MULTILINE)
        if heading:
            return _markdown_plain_text(heading.group(1))
    return ""


def _you_row_summary(row: dict[str, object]) -> str:
    values: list[str] = []
    snippets = row.get("snippets")
    if isinstance(snippets, list):
        values.extend(str(value) for value in snippets if str(value).strip())
    elif isinstance(snippets, str) and snippets.strip():
        values.append(snippets)
    description = row.get("description")
    if isinstance(description, str) and description.strip():
        values.append(description)
    contents = row.get("contents")
    if isinstance(contents, dict):
        markdown = contents.get("markdown")
        if isinstance(markdown, str) and markdown.strip():
            values.append(markdown)
        html = contents.get("html")
        if not values and isinstance(html, str) and html.strip():
            values.append(html)
    for key in ("markdown", "content"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return _markdown_plain_text(" ".join(dict.fromkeys(values)))


def _markdown_plain_text(value: str) -> str:
    without_links = re.sub(r"\[([^\]]+)\]\(https?://[^\s)>]+\)", r"\1", value)
    without_urls = re.sub(r"https?://\S+", " ", without_links)
    without_markup = re.sub(r"(?:^|\s)[#>*_`~-]+(?=\s|$)", " ", without_urls)
    return _plain_text(without_markup)


class YouWebDiscoveryProvider:
    """Optional raw web search through You.com's documented Search endpoint.

    One provider search deliberately makes one HTTP request. This preserves the
    existing per-provider operation/cost ledger contract while adding a broad
    result pool which still passes the same individual-vacancy gate as Exa and
    Brave.
    """

    name = "you-web"
    attribution = "Web results discovered via You.com Search"
    attribution_url = "https://you.com/docs/api-reference/search/v1-search-post"
    endpoint = "https://ydc-index.io/v1/search"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("You.com Search requires a non-empty API key")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": api_key.strip(),
            "User-Agent": _user_agent(),
        }
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)
        self.last_request_count = 0

    @staticmethod
    def maximum_request_count(query: DiscoveryQuery) -> int:
        return 1

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        searches = _web_search_texts(query)
        search_text = searches[0] if searches else f"{query.text} {query.location} job".strip()
        payload: dict[str, object] = {
            "query": search_text,
            "count": min(100, query.limit),
            "freshness": "month",
            "safesearch": "strict",
            "exclude_domains": sorted(WEB_DISCOVERY_EXCLUDED_DOMAINS),
        }
        origin = _PLACE_INDEX.resolve(query.location)
        if origin is not None and not query.worldwide:
            payload["country"] = origin.country_code
        try:
            self.last_request_count = 1
            response = self.client.post(self.endpoint, json=payload)
            response.raise_for_status()
            rows = _you_web_rows(response)
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise DiscoveryError("You.com Search was unavailable for this Explore run.") from exc

        regional_locations = _regional_search_locations(query)
        jobs = [
            parsed
            for row in rows
            if self._usable(row)
            if (parsed := self._parse(row, query, regional_locations)) is not None
        ]
        return _relevant_jobs(query, _deduplicate_jobs(jobs))

    @staticmethod
    def _usable(row: object) -> bool:
        if not isinstance(row, dict):
            return False
        summary = _you_row_summary(row)
        return web_discovery_result_is_plausible_job(
            str(row.get("url") or ""),
            _you_row_title(row),
            summary,
        )

    @staticmethod
    def _parse(
        row: dict[str, object],
        query: DiscoveryQuery,
        regional_locations: list[str],
    ) -> DiscoveredJob | None:
        url = str(row.get("url") or "").strip()
        if web_discovery_url_is_error_landing(url):
            return None
        title = _you_row_title(row)[:500] or "Job opportunity"
        summary = _you_row_summary(row)[:1_500]
        remote = _remote_only_signal(f"{title} {summary}")
        location = _market_safe_web_location(
            title,
            summary,
            query,
            regional_locations,
            remote=remote,
            source_url=url,
        )
        if location is None:
            return None
        tags = ["Source verification required"]
        if web_discovery_matches_portal(url, query):
            tags.insert(0, "Saved employer portal")
        host = (urlsplit(url).hostname or "Employer source").removeprefix("www.")
        return DiscoveredJob(
            provider="you-web",
            external_id=str(row.get("id") or url),
            title=title,
            company=host[:500],
            location=location,
            remote=remote,
            tags=tags,
            summary=summary,
            source_url=url,
            published_at=_parse_datetime(row.get("published_at") or row.get("publishedDate")),
        )


class DiscoverySourceMesh:
    """Combine configured feeds, searches and ATS expansion before local ranking."""

    name = "source-mesh"

    def __init__(
        self,
        primary_providers: Iterable[JobDiscoveryProvider],
        *,
        ats_expander: AtsDiscoveryExpander | None = None,
        fallback_providers: Iterable[JobDiscoveryProvider] = (),
        fallback_min_results: int = 30,
        place_index: OfflinePlaceIndex | None = None,
        availability_filter: DiscoveryAvailabilityFilter | None = None,
        search_budget_seconds: float = 390.0,
        preview_limit: int = 9,
    ) -> None:
        self.primary_providers = list(primary_providers)
        self.ats_expander = ats_expander
        self.fallback_providers = list(fallback_providers)
        self.fallback_min_results = max(1, min(100, fallback_min_results))
        self.place_index = place_index or _PLACE_INDEX
        self.availability_filter = availability_filter
        self.search_budget_seconds = max(30.0, min(420.0, search_budget_seconds))
        self.preview_limit = max(3, min(12, preview_limit))
        self.availability_reserve_seconds = min(40.0, self.search_budget_seconds * 0.2)
        if not self.primary_providers and not self.fallback_providers:
            raise ValueError("the discovery mesh needs at least one source")
        self.attribution = "Discovery Source Mesh"
        self.attribution_url = "https://github.com/ILLVAN/betteroption"
        self.last_fallback_used = False
        self.last_regional_count = 0

    @property
    def attributions(self) -> list[DiscoveryAttribution]:
        sources = [
            DiscoveryAttribution(label=provider.attribution, url=provider.attribution_url)
            for provider in [*self.primary_providers, *self.fallback_providers]
        ]
        if self.ats_expander is not None:
            sources.extend(self.ats_expander.attributions)
        unique: dict[str, DiscoveryAttribution] = {}
        for source in sources:
            unique.setdefault(str(source.url), source)
        return list(unique.values())

    def search(
        self,
        query: DiscoveryQuery,
        *,
        on_preview: Callable[[str, list[DiscoveredJob]], None] | None = None,
        check_control: Callable[[], None] | None = None,
    ) -> list[DiscoveredJob]:
        deadline = time.monotonic() + self.search_budget_seconds
        self.last_fallback_used = False
        self.last_regional_count = 0
        jobs: list[DiscoveredJob] = []
        successes = 0
        errors: list[str] = []

        def emit_preview(stage: str, candidates: list[DiscoveredJob]) -> None:
            if on_preview is None:
                return
            try:
                ranked_preview = finalize_discovered_jobs(
                    query,
                    candidates,
                    place_index=self.place_index,
                )[: min(self.preview_limit, query.limit)]
                on_preview(stage, ranked_preview)
            except Exception:
                # Progressive presentation is intentionally best effort. A
                # presentation failure must never discard provider
                # results or turn an otherwise valid Explore run into a retry.
                # Worker control uses BaseException-derived private signals so
                # it deliberately bypasses this cosmetic error boundary.
                return

        if check_control is not None:
            check_control()

        primary_timeout = min(
            300.0,
            max(0.0, self._remaining(deadline) - self.availability_reserve_seconds),
        )
        if on_preview is None:
            primary_results, primary_errors = self._search_providers(
                self.primary_providers,
                query,
                timeout_seconds=primary_timeout,
                check_control=check_control,
            )
        else:
            primary_results, primary_errors = self._search_providers(
                self.primary_providers,
                query,
                timeout_seconds=primary_timeout,
                on_progress=lambda provider, candidates: emit_preview(provider, candidates),
                check_control=check_control,
            )
        if check_control is not None:
            check_control()
        for result in primary_results:
            jobs.extend(result)
            successes += 1
        errors.extend(primary_errors)

        preliminary = finalize_discovered_jobs(query, jobs, place_index=self.place_index)
        regional_count = _regional_result_count(query, preliminary)
        needs_regional_coverage = (
            query.regional_target > 0
            and not query.remote_only
            and regional_count < query.regional_target
        )
        if (
            (len(preliminary) < self.fallback_min_results or needs_regional_coverage)
            and self.fallback_providers
            and self._remaining(deadline) > self.availability_reserve_seconds
        ):
            fallback_timeout = max(
                0.0,
                self._remaining(deadline) - self.availability_reserve_seconds,
            )
            if on_preview is None:
                fallback_results, fallback_errors = self._search_providers(
                    self.fallback_providers,
                    query,
                    timeout_seconds=fallback_timeout,
                    check_control=check_control,
                )
            else:
                fallback_results, fallback_errors = self._search_providers(
                    self.fallback_providers,
                    query,
                    timeout_seconds=fallback_timeout,
                    on_progress=lambda provider, candidates: emit_preview(
                        provider,
                        [*jobs, *candidates],
                    ),
                    check_control=check_control,
                )
            if check_control is not None:
                check_control()
            for result in fallback_results:
                jobs.extend(result)
                self.last_fallback_used = True
            errors.extend(fallback_errors)

        if (
            self.ats_expander is not None
            and self._remaining(deadline) > self.availability_reserve_seconds
        ):
            try:
                expanded_jobs = self.ats_expander.search(
                    query,
                    jobs,
                    timeout_seconds=min(
                        30.0,
                        max(
                            0.0,
                            self._remaining(deadline) - self.availability_reserve_seconds,
                        ),
                    ),
                    check_control=check_control,
                )
                jobs.extend(expanded_jobs)
                emit_preview("employer_boards", jobs)
            except DiscoveryError as exc:
                errors.append(str(exc))

        ranked = finalize_discovered_jobs(query, jobs, place_index=self.place_index)
        ranked = self._with_source_readiness(
            ranked,
            timeout_seconds=self._remaining(deadline),
            check_control=check_control,
        )
        emit_preview("source_checks", ranked)
        if not successes and not ranked:
            raise DiscoveryError(" ".join(errors) or "No discovery source was available.")
        self.last_regional_count = _regional_result_count(query, ranked)
        return ranked[: query.limit]

    @staticmethod
    def _search_providers(
        providers: list[JobDiscoveryProvider],
        query: DiscoveryQuery,
        *,
        timeout_seconds: float,
        on_progress: Callable[[str, list[DiscoveredJob]], None] | None = None,
        check_control: Callable[[], None] | None = None,
    ) -> tuple[list[list[DiscoveredJob]], list[str]]:
        if not providers or timeout_seconds <= 0:
            return [], []
        # Up to ten configured sources get their own worker so a bounded
        # synchronous actor does not queue the remaining discovery mesh behind
        # it. Larger custom meshes remain bounded to ten concurrent workers.
        executor = DaemonThreadPoolExecutor(
            max_workers=min(10, len(providers)),
            thread_name_prefix="explore-provider",
        )

        def search_provider(provider: JobDiscoveryProvider) -> list[DiscoveredJob]:
            with cooperative_control(check_control):
                return provider.search(query)

        futures = [
            executor.submit(copy_context().run, search_provider, provider) for provider in providers
        ]
        deadline = time.monotonic() + timeout_seconds
        future_indexes = {future: index for index, future in enumerate(futures)}
        pending = set(futures)
        completed_results: dict[int, list[DiscoveredJob]] = {}
        errors: list[str] = []
        try:
            while pending:
                if check_control is not None:
                    check_control()
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                completed, pending = wait(
                    pending,
                    timeout=min(0.25, remaining),
                    return_when=FIRST_COMPLETED,
                )
                if not completed:
                    continue
                for future in sorted(completed, key=future_indexes.__getitem__):
                    index = future_indexes[future]
                    provider = providers[index]
                    try:
                        completed_results[index] = future.result()
                    except (DiscoveryError, BraveSearchError) as exc:
                        errors.append(str(exc))
                        continue
                    if on_progress is not None:
                        accumulated = [
                            job
                            for completed_index in sorted(completed_results)
                            for job in completed_results[completed_index]
                        ]
                        on_progress(provider.name, accumulated)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        for future in pending:
            errors.append(_shared_deadline_error(providers[future_indexes[future]]))
        # Preserve configured order for deterministic collection even though
        # calls complete in parallel. Deduplication later chooses richer
        # evidence and final ranking never awards points for provider identity.
        results = [completed_results[index] for index in sorted(completed_results)]
        return results, errors

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    def _with_source_readiness(
        self,
        jobs: list[DiscoveredJob],
        *,
        timeout_seconds: float | None = None,
        check_control: Callable[[], None] | None = None,
    ) -> list[DiscoveredJob]:
        """Fail raw web closed and annotate structured-source preflight state."""

        if self.availability_filter is None:
            return [job for job in jobs if not _raw_web_only(job)]
        return self.availability_filter.keep_open_or_unknown(
            jobs,
            timeout_seconds=timeout_seconds,
            check_control=check_control,
        )


def _shared_deadline_error(provider: JobDiscoveryProvider) -> str:
    """Return a fixed provider timeout row without reflecting arbitrary data."""

    raw_name = str(getattr(provider, "name", "")).casefold()
    safe_name = (
        raw_name if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", raw_name) else "discovery-provider"
    )
    return f"{safe_name}: shared Explore deadline reached before the provider returned."


def _regional_result_count(query: DiscoveryQuery, jobs: Iterable[DiscoveredJob]) -> int:
    """Count only non-remote roles with a resolved location inside the rough Explore radius."""

    if not query.location.strip():
        return 0
    return sum(
        1
        for job in jobs
        if not job.remote
        and job.distance_km is not None
        and job.distance_km <= query.regional_radius_km
    )


def _relevant_jobs(query: DiscoveryQuery, jobs: Iterable[DiscoveredJob]) -> list[DiscoveredJob]:
    candidates = list(jobs)
    if query.desired_terms:
        return [
            job for job in candidates if discovered_job_has_structured_role_evidence(query, job)
        ][: query.limit]
    wanted = _tokens(query.text)
    if not wanted:
        return candidates[: query.limit]
    relevant: list[DiscoveredJob] = []
    for job in candidates:
        material = _tokens(" ".join((job.title, job.company, job.summary, " ".join(job.tags))))
        if wanted.intersection(material):
            relevant.append(job)
    return relevant[: query.limit]


def _deduplicate_jobs(jobs: Iterable[DiscoveredJob]) -> list[DiscoveredJob]:
    unique: dict[str, DiscoveredJob] = {}
    for job in jobs:
        unique.setdefault(str(job.source_url).casefold().rstrip("/"), job)
    return list(unique.values())


def _unique_boards(boards: Iterable[ConfiguredAtsBoard]) -> list[ConfiguredAtsBoard]:
    unique: dict[tuple[str, str], ConfiguredAtsBoard] = {}
    for board in boards:
        unique.setdefault(board.identity, board)
    return list(unique.values())


def _json_client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        headers={"Accept": "application/json", "User-Agent": _user_agent()},
    )


def _user_agent() -> str:
    return "BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(without_tags.replace("&amp;", "&").split())


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_epoch_milliseconds(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value) / 1_000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
