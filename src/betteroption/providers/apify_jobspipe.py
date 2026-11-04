"""Structured job discovery through the distinct Apify JobsPipe actor.

JobsPipe and EURES are separate discovery products which happen to share an
Apify credential.  This adapter therefore owns its actor endpoint, provider
identity, attribution, accounting counters, and sanitized error taxonomy.  The
Apify token is sent only in an authorization header and is never copied into a
URL, result, exception, or operation record.
"""

from __future__ import annotations

import html
import math
import re
from concurrent.futures import FIRST_COMPLETED, wait
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlsplit

import geonamescache
import httpx

from ..concurrency import DaemonThreadPoolExecutor, check_cooperative_control
from ..discovery import DiscoveredJob, DiscoveryError, DiscoveryQuery
from ..geography import (
    OfflineGermanPostalCodeIndex,
    OfflinePlaceIndex,
    country_code_for_label,
)


_PLACE_INDEX = OfflinePlaceIndex()
_POSTAL_INDEX = OfflineGermanPostalCodeIndex()
_COUNTRIES = geonamescache.GeonamesCache().get_countries()
_TAG_PATTERN = re.compile(r"<[^>]+>")
_KEYWORD_STOPWORDS = frozenset(
    {
        "and",
        "der",
        "die",
        "for",
        "für",
        "in",
        "job",
        "jobs",
        "mit",
        "oder",
        "or",
        "the",
        "und",
    }
)


class JobsPipeError(DiscoveryError):
    """Sanitized JobsPipe-through-Apify failure safe for operation metadata."""


class JobsPipeAuthenticationError(JobsPipeError):
    """Apify rejected the configured token."""


class JobsPipePlanError(JobsPipeError):
    """The Apify account cannot run the JobsPipe actor."""


class JobsPipeRateLimitError(JobsPipeError):
    """The Apify or JobsPipe request allowance was reached."""


class JobsPipeUnavailableError(JobsPipeError):
    """The JobsPipe actor was temporarily unavailable."""


class JobsPipeRequestError(JobsPipeError):
    """The JobsPipe actor rejected a bounded request."""


class JobsPipeResponseError(JobsPipeError):
    """The JobsPipe actor returned an unsupported dataset response."""


class ApifyJobsPipeDiscoveryProvider:
    """Bounded JobsPipe discovery backed by its own Apify actor run."""

    name = "apify-jobspipe"
    attribution = "JobsPipe via Apify"
    attribution_url = "https://apify.com/jobspipe/jobspipe-job-search"
    endpoint = (
        "https://api.apify.com/v2/acts/jobspipe~jobspipe-job-search/run-sync-get-dataset-items"
    )

    def __init__(
        self,
        api_token: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 285.0,
        max_results: int = 300,
        posted_within_days: int = 60,
        max_requests: int = 4,
        search_budget_seconds: float = 240.0,
    ) -> None:
        clean_token = api_token.strip()
        if not clean_token:
            raise ValueError("Apify JobsPipe requires a non-empty API token")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/json",
            "User-Agent": "BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)",
        }
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        )
        self.client.headers.update(headers)
        # JobsPipe can return 500 rows in one upstream page. BetterOption keeps
        # a lower shared 300-candidate ceiling so one nationwide source cannot
        # crowd every regional or direct-employer result out of final ranking.
        self.max_results = max(1, min(300, max_results))
        self.posted_within_days = max(1, min(365, posted_within_days))
        self.max_requests = max(1, min(4, max_requests))
        self.search_budget_seconds = max(10.0, min(240.0, float(search_budget_seconds)))
        self.last_request_count = 0
        self._request_lock = Lock()

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        return len(_request_specs(query, maximum=self.max_requests))

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.last_request_count = 0
        total_limit = min(query.limit, self.max_results)
        specs = _request_specs(query, maximum=self.max_requests)
        per_request_limit = max(1, math.ceil(total_limit / len(specs)))
        request_timeout = httpx.Timeout(
            connect=min(10.0, self.search_budget_seconds),
            read=self.search_budget_seconds,
            write=min(10.0, self.search_budget_seconds),
            pool=min(5.0, self.search_budget_seconds),
        )

        def fetch(spec: dict[str, object]) -> list[object]:
            payload: dict[str, object] = {
                **spec,
                "postedWithinDays": self.posted_within_days,
                "maxItems": per_request_limit,
            }
            if query.remote_only:
                payload["remote"] = True
            with self._request_lock:
                self.last_request_count += 1
            try:
                # Each small actor run uses exactly one documented OR-filter
                # group. Combining title and description groups makes them AND
                # filters and was the main reason broad results disappeared.
                response = self.client.post(
                    self.endpoint,
                    params={"maxItems": per_request_limit},
                    json=payload,
                    timeout=request_timeout,
                )
                _raise_for_status(response)
                rows = response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise JobsPipeUnavailableError(
                    "JobsPipe discovery through Apify was temporarily unreachable."
                ) from exc
            except ValueError as exc:
                raise JobsPipeResponseError(
                    "JobsPipe discovery through Apify returned invalid JSON."
                ) from exc
            except JobsPipeError:
                raise
            except httpx.HTTPError as exc:
                raise JobsPipeRequestError(
                    "JobsPipe discovery through Apify could not complete its request."
                ) from exc
            if not isinstance(rows, list):
                raise JobsPipeResponseError(
                    "JobsPipe discovery through Apify returned an unsupported dataset response."
                )
            return rows

        # Four synchronous actor runs would multiply the 285-second actor
        # ceiling. Run the independently billed, pre-reserved calls in parallel
        # so the provider remains under one explicit Explore-scale time bound.
        executor = DaemonThreadPoolExecutor(
            max_workers=len(specs),
            thread_name_prefix="jobspipe-request",
        )
        futures = [executor.submit(fetch, spec) for spec in specs]
        pending = set(futures)
        all_completed = False
        try:
            while pending:
                check_cooperative_control()
                _completed, pending = wait(
                    pending,
                    timeout=0.25,
                    return_when=FIRST_COMPLETED,
                )
            all_completed = True
        finally:
            executor.shutdown(
                wait=all_completed,
                cancel_futures=not all_completed,
            )

        jobs: list[DiscoveredJob] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        successful_requests = 0
        first_error: JobsPipeError | None = None
        for future in futures:
            try:
                rows = future.result()
                successful_requests += 1
            except JobsPipeError as exc:
                first_error = first_error or exc
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                parsed = _parse_row(row)
                if parsed is None:
                    continue
                identity = parsed.external_id.casefold()
                source_url = str(parsed.source_url).casefold()
                if identity in seen_ids or source_url in seen_urls:
                    continue
                seen_ids.add(identity)
                seen_urls.add(source_url)
                jobs.append(parsed)
                if len(jobs) >= total_limit:
                    break
            if len(jobs) >= total_limit:
                break
        if successful_requests == 0 and first_error is not None:
            raise first_error
        return jobs


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 401:
        raise JobsPipeAuthenticationError(
            "Apify rejected the configured token for JobsPipe discovery."
        )
    if status in {402, 403}:
        raise JobsPipePlanError("The Apify account is not entitled to run the JobsPipe actor.")
    if status == 429:
        raise JobsPipeRateLimitError(
            "JobsPipe discovery through Apify reached its current request limit."
        )
    if status >= 500:
        raise JobsPipeUnavailableError(
            "JobsPipe discovery through Apify was temporarily unavailable."
        )
    if response.is_error:
        raise JobsPipeRequestError(
            f"JobsPipe discovery through Apify rejected the request (HTTP {status})."
        )


def _request_specs(query: DiscoveryQuery, *, maximum: int) -> list[dict[str, object]]:
    """Build small independent OR-group searches under one total result cap."""

    title_sources = list(query.desired_terms[:3]) or [query.text]
    title_keywords = _single_keywords(title_sources, maximum=3)
    skill_keywords = _single_keywords(query.desired_terms[3:], maximum=1)
    if not title_keywords:
        title_keywords = _single_keywords([query.text], maximum=3)
    if not title_keywords:
        title_keywords = ["work"]

    local_countries = _country_codes(query)
    content_limit = maximum - 1 if local_countries and maximum > 1 else maximum
    skill_slots = 1 if skill_keywords and content_limit > 1 else 0
    title_slots = max(1, content_limit - skill_slots)
    specs: list[dict[str, object]] = []
    for keyword in title_keywords[:title_slots]:
        specs.append({"searchTerms": [keyword], "countries": local_countries})
    for keyword in skill_keywords[:skill_slots]:
        specs.append({"descriptionKeywords": [keyword], "countries": local_countries})

    # A final country-free request is intentional: JobsPipe has no city or
    # radius input, while local post-ranking can still surface a strong nearby
    # Swiss/Austrian vacancy for a Munich origin. It uses the best title token
    # and never combines title and description filters.
    if local_countries and len(specs) < maximum:
        specs.append({"searchTerms": [title_keywords[0]], "countries": []})

    return specs[:maximum]


def _single_keywords(candidates: list[str], *, maximum: int) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        for token in re.findall(r"[^\W\d_][\w+#.-]*", str(candidate), flags=re.UNICODE):
            clean = token.strip(".-")[:60]
            folded = clean.casefold()
            if len(clean) < 2 or folded in _KEYWORD_STOPWORDS or folded in seen:
                continue
            seen.add(folded)
            keywords.append(clean)
            if len(keywords) >= maximum:
                break
        if len(keywords) >= maximum:
            break
    return keywords


def _country_codes(query: DiscoveryQuery) -> list[str]:
    if query.worldwide or not query.location.strip():
        return []
    clean = " ".join(query.location.split())
    country_code = country_code_for_label(clean)
    if country_code:
        return [country_code]
    resolved = _POSTAL_INDEX.resolve(clean) or _PLACE_INDEX.resolve_for_explore(clean)
    return [resolved.country_code.upper()] if resolved is not None else []


def _parse_row(row: dict[str, object]) -> DiscoveredJob | None:
    title = _plain_text(row.get("job_title") or row.get("title"))[:500]
    source_url = _first_http_url(
        row.get("final_url"),
        row.get("apply_url"),
        row.get("url"),
        row.get("job_url"),
    )
    if not title or source_url is None:
        return None

    external_id = _plain_text(row.get("id") or row.get("job_id")) or source_url
    company = _plain_text(row.get("company") or row.get("company_name"))
    if not company:
        company = (urlsplit(source_url).hostname or "Employer").removeprefix("www.")
    location = _location(row)
    remote = _as_bool(row.get("remote") or row.get("is_remote"))
    if not remote and "remote" in location.casefold():
        remote = True

    tags = ["JobsPipe"]
    source = _plain_text(row.get("source"))
    if source:
        tags.append(f"Source: {source}"[:100])
    for value in _list_values(
        row.get("employment_type") or row.get("employment_types"),
        row.get("seniority"),
        row.get("occupation_label"),
        row.get("technology_slugs"),
        row.get("keyword_slugs"),
    ):
        clean = _plain_text(value)[:100]
        if clean and clean.casefold() not in {item.casefold() for item in tags}:
            tags.append(clean)
        if len(tags) >= 12:
            break

    description = _plain_text(row.get("description") or row.get("job_description"))
    summary = _bounded_summary(description, _salary_detail(row))
    try:
        return DiscoveredJob(
            provider=ApifyJobsPipeDiscoveryProvider.name,
            external_id=external_id[:500],
            title=title,
            company=company[:500],
            location=location[:500],
            remote=remote,
            tags=tags,
            summary=summary,
            source_url=source_url,
            published_at=_published_at(
                row.get("date_posted") or row.get("posted_at") or row.get("published_at")
            ),
        )
    except ValueError:
        return None


def _location(row: dict[str, object]) -> str:
    value = row.get("location") or row.get("job_location")
    if isinstance(value, dict):
        rendered = [
            _plain_text(value.get(key))
            for key in ("city", "region", "state", "country", "country_code")
        ]
        clean = ", ".join(dict.fromkeys(item for item in rendered if item))
    else:
        clean = _plain_text(value)
    if clean:
        return clean
    city_region = _join_distinct(row.get("city"), row.get("region"), row.get("state"))
    country_code = _plain_text(row.get("country_code") or row.get("job_country_code")).upper()
    country = _country_name(country_code)
    return _join_distinct(city_region, country) or "Location not stated"


def _country_name(code: str) -> str:
    country = _COUNTRIES.get(code)
    return str(country.get("name") or "") if country else code


def _salary_detail(row: dict[str, object]) -> str:
    salary = _plain_text(row.get("salary_string") or row.get("salary"))
    if salary:
        return f"Salary: {salary}"[:300]
    minimum = _number(row.get("min_annual_salary_usd"))
    maximum = _number(row.get("max_annual_salary_usd"))
    if minimum is not None and maximum is not None:
        return f"Salary: USD {minimum:,.0f}–{maximum:,.0f} per year"
    if minimum is not None:
        return f"Salary: from USD {minimum:,.0f} per year"
    if maximum is not None:
        return f"Salary: up to USD {maximum:,.0f} per year"
    return ""


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


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # Zero is the common schema/example placeholder for an unknown salary; it
    # must not become a misleading public ``USD 0`` range in Explore evidence.
    return number if number > 0 else None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().casefold() in {"1", "remote", "true", "yes"}


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
    for value in values:
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


def _join_distinct(*values: object) -> str:
    clean_values: list[str] = []
    for value in values:
        clean = _plain_text(value)
        if clean and clean.casefold() not in {item.casefold() for item in clean_values}:
            clean_values.append(clean)
    return ", ".join(clean_values)
