"""Structured European vacancy discovery through the Apify EURES actor.

Only public vacancy fields documented by the actor are mapped. The Apify token
is sent in an authorization header and is never copied into a URL, result,
exception, or operation record.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
import geonamescache

from ..discovery import DiscoveredJob, DiscoveryError, DiscoveryQuery
from ..geography import OfflineNutsRegionIndex, OfflinePlaceIndex


_PLACE_INDEX = OfflinePlaceIndex()
_NUTS_INDEX = OfflineNutsRegionIndex()
_COUNTRIES = geonamescache.GeonamesCache().get_countries()
_EMAIL_PATTERN = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
_TAG_PATTERN = re.compile(r"<[^>]+>")


class ApifyEuresDiscoveryProvider:
    """Bounded, optional EURES discovery backed by one Apify actor run."""

    name = "apify-eures"
    attribution = "European public vacancies via EURES / Apify"
    attribution_url = "https://apify.com/benthepythondev/eures-jobs-scraper"
    endpoint = (
        "https://api.apify.com/v2/acts/"
        "benthepythondev~eures-jobs-scraper/run-sync-get-dataset-items"
    )

    def __init__(
        self,
        api_token: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 120.0,
        max_results: int = 30,
    ) -> None:
        clean_token = api_token.strip()
        if not clean_token:
            raise ValueError("Apify EURES requires a non-empty API token")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/json",
            "User-Agent": ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        }
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)
        self.max_results = max(1, min(30, max_results))
        self.last_request_count = 0

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        del query
        return 1

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.last_request_count = 0
        payload = {
            "keywords": _keywords(query),
            "countryCodes": _country_codes(query),
            "workingTimeCodes": [],
            "contractTypeCodes": [],
            "maxResults": min(query.limit, self.max_results),
        }
        try:
            self.last_request_count = 1
            response = self.client.post(self.endpoint, json=payload)
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError("Apify EURES response was not a JSON list")
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            # Do not surface third-party bodies: they can echo request metadata
            # or credentials and operation telemetry needs only the error type.
            raise DiscoveryError("EURES discovery through Apify was unavailable.") from exc

        jobs: list[DiscoveredJob] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed = _parse_row(row)
            if parsed is None or parsed.external_id.casefold() in seen:
                continue
            seen.add(parsed.external_id.casefold())
            jobs.append(parsed)
            if len(jobs) >= min(query.limit, self.max_results):
                break
        return jobs


def _keywords(query: DiscoveryQuery) -> list[str]:
    terms: list[str] = []
    for candidate in [
        *query.desired_terms,
        *re.split(r"\s*[·;\n|]\s*", query.text),
    ]:
        clean = " ".join(str(candidate).split())[:120]
        if len(clean) < 2 or clean.casefold() in {item.casefold() for item in terms}:
            continue
        terms.append(clean)
        if len(terms) >= 4:
            break
    return terms or [" ".join(query.text.split())[:120]]


def _country_codes(query: DiscoveryQuery) -> list[str]:
    if query.worldwide or not query.location.strip():
        return []
    clean = query.location.strip()
    if re.fullmatch(r"[A-Za-z]{2}", clean):
        return [clean.upper()]
    resolved = _PLACE_INDEX.resolve(clean)
    return [resolved.country_code.upper()] if resolved is not None else []


def _parse_row(row: dict[str, object]) -> DiscoveredJob | None:
    title = _plain_text(row.get("title"))[:500]
    external_id = _plain_text(row.get("id"))
    canonical_url = _http_url(row.get("url"))
    application_url = _first_http_url(
        row.get("application_url"),
        row.get("application_urls"),
    )
    source_url = canonical_url or application_url
    if not title or not external_id or source_url is None:
        return None

    company = _plain_text(row.get("employer_name")) or "Employer not stated"
    location = _location(row)
    contacts = _contacts(row)
    public_details: list[str] = []
    if application_url is not None and application_url != source_url:
        public_details.append(f"Application: {application_url}")
    if contacts:
        public_details.append(f"Public application contact: {'; '.join(contacts)}")
    summary = _bounded_summary(
        _plain_text(row.get("description") or row.get("description_html")),
        public_details,
    )

    tags = ["EURES"]
    for value in _list_values(
        row.get("working_time_codes"),
        row.get("contract_type_code"),
        row.get("available_languages"),
    ):
        clean = _plain_text(value)[:100]
        if clean and clean.casefold() not in {item.casefold() for item in tags}:
            tags.append(clean)

    try:
        return DiscoveredJob(
            provider=ApifyEuresDiscoveryProvider.name,
            external_id=external_id[:500],
            title=title,
            company=company[:500],
            location=location[:500],
            remote=bool(row.get("remote") or row.get("is_remote")),
            tags=tags[:12],
            summary=summary,
            source_url=source_url,
            published_at=_created_at(row.get("created_at")),
        )
    except ValueError:
        return None


def _location(row: dict[str, object]) -> str:
    for key in ("location", "location_name"):
        clean = _render_location(row.get(key))
        if clean:
            return clean
    locations = row.get("locations")
    if isinstance(locations, list):
        rendered = [_render_location(item) for item in locations]
        clean_locations = [item for item in rendered if item]
        if clean_locations:
            return " / ".join(clean_locations[:3])
    rendered = _render_location(locations)
    if rendered:
        return rendered
    country_codes = _clean_values(_list_values(row.get("country_codes")))
    location_codes = _clean_values(_list_values(row.get("location_codes")))
    rendered_regions = _render_nuts_codes(location_codes)
    if rendered_regions:
        country_names = _country_names(country_codes)
        suffix = country_names[0] if len(country_names) == 1 else ""
        rendered = " / ".join(rendered_regions[:3])
        return (
            f"{rendered}, {suffix}"
            if suffix and suffix.casefold() not in rendered.casefold()
            else rendered
        )
    country_names = _country_names(country_codes)
    return " / ".join(country_names) or "Location not stated"


def _render_location(value: object) -> str:
    if isinstance(value, dict):
        rendered = [
            _plain_text(value.get(key)) for key in ("city", "region", "country", "name", "label")
        ]
        return ", ".join(dict.fromkeys(item for item in rendered if item))
    clean = _plain_text(value)
    region = _NUTS_INDEX.resolve_code(clean)
    if region is None:
        return clean
    country = _country_name(region.country_code)
    return f"{region.label}, {country}" if country else region.label


def _render_nuts_codes(codes: list[str]) -> list[str]:
    """Render the most-specific official regions without repeating parents."""

    normalized = list(dict.fromkeys(code.strip().upper() for code in codes if code.strip()))
    most_specific = [
        code
        for code in normalized
        if not any(other != code and other.startswith(code) for other in normalized)
    ]
    rendered: list[str] = []
    for code in most_specific:
        region = _NUTS_INDEX.resolve_code(code)
        label = region.label if region is not None else ""
        if label and label.casefold() not in {item.casefold() for item in rendered}:
            rendered.append(label)
    return rendered


def _country_names(codes: list[str]) -> list[str]:
    names: list[str] = []
    for code in codes:
        name = _country_name(code)
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return names


def _country_name(code: str) -> str:
    iso_code = {"EL": "GR", "UK": "GB"}.get(code.upper(), code.upper())
    country = _COUNTRIES.get(iso_code)
    return str(country.get("name") or "") if country else ""


def _contacts(row: dict[str, object]) -> list[str]:
    contacts: list[str] = []
    for value in _list_values(row.get("contact_email"), row.get("contact_emails")):
        contacts.extend(_EMAIL_PATTERN.findall(str(value)))
    for value in _list_values(row.get("contact_phone"), row.get("contact_phones")):
        phone = re.sub(r"[^0-9+() /.-]", "", str(value)).strip()
        if sum(character.isdigit() for character in phone) >= 6:
            contacts.append(phone[:60])
    return list(dict.fromkeys(contacts))[:5]


def _bounded_summary(description: str, public_details: list[str]) -> str:
    extra = " · ".join(public_details)[:500]
    if not extra:
        return description[:1_500]
    available = max(0, 1_500 - len(extra) - 3)
    body = description[:available].rstrip()
    return f"{body} · {extra}" if body else extra


def _created_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _plain_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(_TAG_PATTERN.sub(" ", str(value)))
    return " ".join(text.split())


def _http_url(value: object) -> str | None:
    clean = str(value or "").strip()
    try:
        parsed = urlsplit(clean)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    return clean


def _first_http_url(*values: object) -> str | None:
    for value in _list_values(*values):
        parsed = _http_url(value)
        if parsed is not None:
            return parsed
    return None


def _list_values(*values: object) -> list[object]:
    flattened: list[object] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            flattened.extend(value)
        elif value not in (None, ""):
            flattened.append(value)
    return flattened


def _clean_values(values: list[object]) -> list[str]:
    return [clean for value in values if (clean := _plain_text(value))]
