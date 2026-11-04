"""Multi-platform job discovery through AgentX's All Jobs Scraper actor.

The actor normalizes public vacancies from multiple job boards into one
dataset.  BetterOption deliberately maps only vacancy, company, salary, and
source fields.  The actor's contact-email, phone, and social-link enrichment is
not copied into Explore results.  The Apify token is sent only in the
``Authorization`` header and never enters a URL, payload, result, or error.
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit

import geonamescache
import httpx

from ..discovery import DiscoveredJob, DiscoveryError, DiscoveryQuery
from ..geography import (
    OfflineGermanPostalCodeIndex,
    OfflinePlaceIndex,
    country_code_for_label,
)


_PLACE_INDEX = OfflinePlaceIndex()
_POSTAL_INDEX = OfflineGermanPostalCodeIndex()
_COUNTRIES = geonamescache.GeonamesCache().get_countries()
_COUNTRY_NAMES = {
    str(country.get("name") or "").casefold(): str(country.get("name") or "")
    for country in _COUNTRIES.values()
    if country.get("name")
}
_TAG_PATTERN = re.compile(r"<[^>]+>")


class AllJobsError(DiscoveryError):
    """Sanitized AgentX-through-Apify failure safe for operation metadata."""


class AllJobsAuthenticationError(AllJobsError):
    """Apify rejected the configured token."""


class AllJobsPlanError(AllJobsError):
    """The Apify account cannot run the AgentX actor."""


class AllJobsRateLimitError(AllJobsError):
    """The Apify or actor request allowance was reached."""


class AllJobsUnavailableError(AllJobsError):
    """The AgentX actor was temporarily unavailable."""


class AllJobsRequestError(AllJobsError):
    """The AgentX actor rejected a bounded request."""


class AllJobsResponseError(AllJobsError):
    """The AgentX actor returned an unsupported dataset response."""


class ApifyAllJobsDiscoveryProvider:
    """Bounded multi-board discovery backed by one AgentX actor run."""

    name = "apify-all-jobs"
    attribution = "All Jobs Scraper via Apify"
    attribution_url = "https://apify.com/agentx/all-jobs-scraper"
    endpoint = "https://api.apify.com/v2/acts/agentx~all-jobs-scraper/runs"
    run_endpoint = "https://api.apify.com/v2/actor-runs/{run_id}"
    dataset_endpoint = "https://api.apify.com/v2/datasets/{dataset_id}/items"
    _terminal_statuses = frozenset({"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"})

    def __init__(
        self,
        api_token: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 285.0,
        max_results_per_platform: int = 20,
        max_items: int = 120,
        max_total_charge_usd: float = 0.40,
        posted_since: str = "30 days",
        platforms: Sequence[str] | str | None = None,
        distance_miles: int | None = None,
        country: str = "",
    ) -> None:
        clean_token = api_token.strip()
        if not clean_token:
            raise ValueError("Apify All Jobs Scraper requires a non-empty API token")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/json",
            "User-Agent": "BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)",
        }
        self.timeout_seconds = max(1.0, min(285.0, float(timeout_seconds)))
        self.client = client or httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)
        # max_results is applied per selected platform and drives potential
        # pay-per-event volume. maxItems separately bounds API readback and
        # presentation; only maxTotalChargeUsd is the monetary actor-run cap.
        self.max_results_per_platform = max(1, min(500, max_results_per_platform))
        self.max_items = max(1, min(300, max_items))
        self.max_total_charge_usd = max(0.0, float(max_total_charge_usd))
        self.posted_since = " ".join(posted_since.split())[:40]
        self.platforms = _platform_names(platforms)
        self.distance_miles = (
            None if distance_miles is None else max(50, min(10_000, int(distance_miles)))
        )
        self.default_country = " ".join(country.split())[:100]
        self.last_request_count = 0

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        del query
        # The start request waits for the first minute. Poll the same paid run
        # for the remaining actor window, then fetch its one dataset.
        return 2 + max(0, math.ceil(self.timeout_seconds / 60.0) - 1)

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.last_request_count = 0
        item_limit = min(query.limit, self.max_items)
        country = _country_name(query.location) or _normalized_country(self.default_country)
        if not country:
            raise AllJobsRequestError(
                "All Jobs Scraper requires a location with a resolvable country."
            )

        payload: dict[str, object] = {
            "max_results": min(self.max_results_per_platform, item_limit),
            "keyword": _keyword(query),
            "country": country,
        }
        location = _raw_location(query.location, country=country)
        if location and not query.worldwide:
            payload["location"] = location
        if query.remote_only:
            payload["remote_only"] = True
        if self.posted_since:
            payload["posted_since"] = self.posted_since
        if self.platforms:
            payload["platforms"] = list(self.platforms)
        distance = self._distance_for(query, has_location="location" in payload)
        if distance is not None:
            payload["distance"] = distance

        # maxItems protects bounded readback/presentation, but is not a billing
        # ceiling. maxTotalChargeUsd below is the actor's pay-per-event cap.
        params: dict[str, int | float] = {
            "maxItems": item_limit,
            "timeout": int(self.timeout_seconds),
            "waitForFinish": min(60, int(self.timeout_seconds)),
        }
        if self.max_total_charge_usd > 0:
            params["maxTotalChargeUsd"] = self.max_total_charge_usd

        response = self._request("POST", self.endpoint, params=params, json=payload)
        state = _run_state(response)
        run_id = _safe_apify_id(state.get("id"))
        dataset_id = _safe_apify_id(state.get("defaultDatasetId"))
        status = _run_status(state)

        # Keep polling the same actor run; never start an automatic paid rerun.
        # Apify's synchronous dataset endpoint has a hard 300-second ceiling,
        # while this sequence remains inspectable and can recover partial rows.
        remaining_polls = max(0, math.ceil(self.timeout_seconds / 60.0) - 1)
        while status not in self._terminal_statuses and remaining_polls > 0:
            if not run_id:
                raise AllJobsResponseError(
                    "All Jobs Scraper returned an unsupported actor-run response."
                )
            response = self._request(
                "GET",
                self.run_endpoint.format(run_id=run_id),
                params={"waitForFinish": 60},
            )
            state = _run_state(response)
            status = _run_status(state)
            dataset_id = _safe_apify_id(state.get("defaultDatasetId")) or dataset_id
            remaining_polls -= 1

        if not dataset_id:
            if status == "SUCCEEDED":
                raise AllJobsResponseError(
                    "All Jobs Scraper completed without a readable dataset reference."
                )
            raise AllJobsUnavailableError(
                "All Jobs Scraper did not produce a readable dataset in its bounded run."
            )

        rows = self._dataset_rows(dataset_id, item_limit=item_limit)
        if status != "SUCCEEDED" and not rows:
            raise AllJobsUnavailableError(
                "All Jobs Scraper did not complete and returned no usable partial dataset."
            )

        jobs: list[DiscoveredJob] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            parsed = _parse_row(row)
            if parsed is None:
                continue
            identity = parsed.external_id.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            jobs.append(parsed)
            if len(jobs) >= item_limit:
                break
        return jobs

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, int | float],
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        try:
            self.last_request_count += 1
            response = self.client.request(method, url, params=params, json=json)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AllJobsUnavailableError(
                "All Jobs Scraper discovery through Apify was temporarily unreachable."
            ) from exc
        except httpx.HTTPError as exc:
            raise AllJobsRequestError(
                "All Jobs Scraper discovery through Apify could not complete its request."
            ) from exc
        _raise_for_status(response)
        return response

    def _dataset_rows(self, dataset_id: str, *, item_limit: int) -> list[object]:
        response = self._request(
            "GET",
            self.dataset_endpoint.format(dataset_id=dataset_id),
            params={"clean": 1, "limit": item_limit},
        )
        try:
            rows = response.json()
        except ValueError as exc:
            raise AllJobsResponseError(
                "All Jobs Scraper discovery through Apify returned invalid JSON."
            ) from exc
        if not isinstance(rows, list):
            raise AllJobsResponseError(
                "All Jobs Scraper discovery through Apify returned an unsupported dataset response."
            )
        return rows

    def _distance_for(self, query: DiscoveryQuery, *, has_location: bool) -> int | None:
        if not has_location:
            return None
        if self.distance_miles is not None:
            return self.distance_miles
        # The actor's minimum is 50 miles.  BetterOption still applies the
        # user's precise kilometre radius after normalization and ranking.
        converted = math.ceil(query.regional_radius_km / 1.609344)
        return max(50, min(10_000, converted))


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 401:
        raise AllJobsAuthenticationError(
            "Apify rejected the configured token for All Jobs Scraper discovery."
        )
    if status in {402, 403}:
        raise AllJobsPlanError(
            "The Apify account is not entitled to run the All Jobs Scraper actor."
        )
    if status == 429:
        raise AllJobsRateLimitError(
            "All Jobs Scraper discovery through Apify reached its current request limit."
        )
    if status == 408 or status >= 500:
        raise AllJobsUnavailableError(
            "All Jobs Scraper discovery through Apify was temporarily unavailable."
        )
    if response.is_error:
        raise AllJobsRequestError(
            f"All Jobs Scraper discovery through Apify rejected the request (HTTP {status})."
        )


def _run_state(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AllJobsResponseError(
            "All Jobs Scraper discovery through Apify returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise AllJobsResponseError("All Jobs Scraper returned an unsupported actor-run response.")
    return payload["data"]


def _safe_apify_id(value: object) -> str:
    clean = str(value or "").strip()
    return clean if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", clean) else ""


def _run_status(state: dict[str, object]) -> str:
    status = str(state.get("status") or "").strip().upper()
    if status not in {
        "READY",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "TIMING-OUT",
        "TIMED-OUT",
        "ABORTING",
        "ABORTED",
    }:
        raise AllJobsResponseError("All Jobs Scraper returned an unsupported actor-run status.")
    return status


def _keyword(query: DiscoveryQuery) -> str:
    candidates = [
        *query.desired_terms,
        *re.split(r"\s*[·|;,\n]\s*|\s+\bor\b\s+", query.text, flags=re.I),
    ]
    for candidate in candidates:
        clean = " ".join(str(candidate).split())
        clean = re.sub(r"(?i)\bjobs?\b", " ", clean)
        clean = " ".join(clean.split())[:160]
        if len(clean) >= 2:
            return clean
    return " ".join(query.text.split())[:160]


def _country_name(location: str) -> str:
    clean = " ".join(location.split())
    if not clean:
        return ""
    country_code = country_code_for_label(clean)
    if country_code:
        return _country_name_for_code(country_code)
    exact = _COUNTRY_NAMES.get(clean.casefold())
    if exact:
        return exact
    resolved = _POSTAL_INDEX.resolve(clean) or _PLACE_INDEX.resolve_for_explore(clean)
    return _country_name_for_code(resolved.country_code) if resolved is not None else ""


def _normalized_country(value: str) -> str:
    clean = " ".join(value.split())
    country_code = country_code_for_label(clean)
    if country_code:
        return _country_name_for_code(country_code)
    return _COUNTRY_NAMES.get(clean.casefold(), clean)


def _country_name_for_code(code: str) -> str:
    country = _COUNTRIES.get(code.strip().upper())
    return str(country.get("name") or "") if country else ""


def _raw_location(value: str, *, country: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    normalized = " ".join(clean.split())
    if country_code_for_label(normalized):
        return ""
    if normalized.casefold() == country.casefold():
        return ""
    return clean[:200]


def _platform_names(value: Sequence[str] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    candidates = (
        re.split(r"\s*[,;|\n]\s*", value)
        if isinstance(value, str)
        else [str(item) for item in value]
    )
    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = " ".join(candidate.split())[:80]
        folded = clean.casefold()
        if not clean or folded in seen:
            continue
        seen.add(folded)
        names.append(clean)
        if len(names) >= 39:
            break
    return tuple(names)


def _parse_row(row: dict[str, object]) -> DiscoveredJob | None:
    # Only documented public vacancy fields are read.  In particular, emails,
    # phones, social_links, processor, and processed_at are intentionally absent.
    title = _plain_text(row.get("title"))[:500]
    source_url = _first_http_url(row.get("official_url"), row.get("platform_url"))
    if not title or source_url is None:
        return None

    company = _plain_text(row.get("company_name"))
    if not company:
        company = (urlsplit(source_url).hostname or "Employer").removeprefix("www.")
    location = _location(row.get("location")) or "Location not stated"
    remote = _as_bool(row.get("is_remote"))
    work_from_home = _plain_text(row.get("work_from_home"))
    if not remote and re.search(r"(?i)\b(remote|hybrid|home office)\b", work_from_home):
        remote = True

    tags = ["All Jobs Scraper"]
    platform = _plain_text(row.get("platform"))
    if platform:
        tags.append(f"Source: {platform}"[:100])
    for value in _tag_values(
        row.get("job_type"),
        row.get("job_level"),
        row.get("job_function"),
        row.get("skills"),
    ):
        clean = _plain_text(value)[:100]
        if clean and clean.casefold() not in {tag.casefold() for tag in tags}:
            tags.append(clean)
        if len(tags) >= 12:
            break

    summary = _bounded_summary(
        _plain_text(row.get("description")),
        _salary_detail(row),
    )
    try:
        return DiscoveredJob(
            provider=ApifyAllJobsDiscoveryProvider.name,
            external_id=source_url[:500],
            title=title,
            company=company[:500],
            location=location[:500],
            remote=remote,
            tags=tags[:12],
            summary=summary,
            source_url=source_url,
            published_at=_published_at(row.get("posted_date")),
        )
    except ValueError:
        return None


def _location(value: object) -> str:
    if isinstance(value, dict):
        raw = _plain_text(value.get("raw"))
        if raw:
            return raw
        return _join_distinct(
            value.get("locality"),
            value.get("region"),
            value.get("postal_code"),
            value.get("country"),
            value.get("country_code"),
        )
    return _plain_text(value)


def _salary_detail(row: dict[str, object]) -> str:
    minimum = _positive_number(row.get("salary_minimum"))
    maximum = _positive_number(row.get("salary_maximum"))
    if minimum is None and maximum is None:
        return ""
    currency = _plain_text(row.get("salary_currency")).upper()[:10] or "Salary"
    period = _salary_period_label(row.get("salary_period"))
    suffix = f" per {period}" if period else ""
    if minimum is not None and maximum is not None:
        return f"Salary: {currency} {minimum:,.0f}–{maximum:,.0f}{suffix}"
    if minimum is not None:
        return f"Salary: from {currency} {minimum:,.0f}{suffix}"
    return f"Salary: up to {currency} {maximum:,.0f}{suffix}"


def _salary_period_label(value: object) -> str:
    raw = _plain_text(value).casefold()[:40]
    return {
        "annually": "year",
        "annual": "year",
        "yearly": "year",
        "monthly": "month",
        "weekly": "week",
        "daily": "day",
        "hourly": "hour",
    }.get(raw, raw)


def _bounded_summary(description: str, detail: str) -> str:
    if not detail:
        return description[:1_500]
    available = max(0, 1_500 - len(detail) - 3)
    body = description[:available].rstrip()
    return f"{body} · {detail}" if body else detail


def _published_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _plain_text(value: object) -> str:
    text = html.unescape(_TAG_PATTERN.sub(" ", str(value or "")))
    return " ".join(text.split())


def _first_http_url(*values: object) -> str | None:
    for value in values:
        clean = str(value or "").strip()
        try:
            parsed = urlsplit(clean)
        except ValueError:
            continue
        if parsed.scheme.casefold() in {"http", "https"} and parsed.hostname:
            return clean
    return None


def _join_distinct(*values: object) -> str:
    rendered: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _plain_text(value)
        folded = clean.casefold()
        if clean and folded not in seen:
            seen.add(folded)
            rendered.append(clean)
    return ", ".join(rendered)


def _tag_values(*values: object) -> list[object]:
    rendered: list[object] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            rendered.extend(value)
        elif isinstance(value, str) and "," in value:
            rendered.extend(value.split(","))
        elif value not in (None, ""):
            rendered.append(value)
    return rendered
