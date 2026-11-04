"""Structured job discovery through OpenWebNinja's JSearch API.

The adapter deliberately consumes only the documented search-v2 response and
returns source links which remain inspectable by the candidate.  API keys never
enter a query, stored result, operation row, or exception message.
"""

from __future__ import annotations

import html
import re
import socket
import ssl
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from time import monotonic, sleep
from urllib.parse import urlsplit

import httpx

from ..discovery import DiscoveredJob, DiscoveryError, DiscoveryQuery
from ..geography import (
    OfflineGermanPostalCodeIndex,
    OfflinePlaceIndex,
    country_code_for_label,
)


_PLACE_INDEX = OfflinePlaceIndex()
_POSTAL_INDEX = OfflineGermanPostalCodeIndex()
_MARKET_LANGUAGES = {
    "AT": "de",
    "BE": "nl",
    "BG": "bg",
    "CH": "de",
    "CZ": "cs",
    "DE": "de",
    "DK": "da",
    "ES": "es",
    "FI": "fi",
    "FR": "fr",
    "GB": "en",
    "GR": "el",
    "HU": "hu",
    "IE": "en",
    "IT": "it",
    "NL": "nl",
    "NO": "no",
    "PL": "pl",
    "PT": "pt",
    "RO": "ro",
    "SE": "sv",
    "SK": "sk",
}
_ROLE_MARKERS = frozenset(
    {
        "administrator",
        "analyst",
        "architect",
        "consultant",
        "designer",
        "developer",
        "engineer",
        "entwickler",
        "ingenieur",
        "manager",
        "researcher",
        "scientist",
        "specialist",
        "technician",
        "tester",
    }
)
_RETRYABLE_STATUS_CODES = frozenset({429, *range(500, 600)})
_SUCCESS_ENVELOPE_STATUSES = frozenset({"ok", "success", "successful", "true", "200"})
_FAILURE_ENVELOPE_STATUSES = frozenset({"error", "failed", "failure", "false"})
_AUTHENTICATION_ERROR_CODES = frozenset(
    {
        "401",
        "authentication_error",
        "invalid_api_key",
        "invalid_key",
        "unauthenticated",
        "unauthorized",
    }
)
_PLAN_ERROR_CODES = frozenset(
    {
        "402",
        "403",
        "forbidden",
        "payment_required",
        "plan_limit",
        "subscription_required",
    }
)
_RATE_LIMIT_ERROR_CODES = frozenset(
    {
        "429",
        "quota_exceeded",
        "rate_limit",
        "rate_limit_exceeded",
        "too_many_requests",
    }
)
_UNAVAILABLE_ERROR_CODES = frozenset(
    {
        "500",
        "502",
        "503",
        "504",
        "service_unavailable",
        "temporarily_unavailable",
    }
)

DEFAULT_JSEARCH_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_JSEARCH_READ_TIMEOUT_SECONDS = 90.0
DEFAULT_JSEARCH_WRITE_TIMEOUT_SECONDS = 10.0
DEFAULT_JSEARCH_POOL_TIMEOUT_SECONDS = 5.0
# DiscoverySourceMesh gives primary sources at most 300 seconds. A much smaller
# provider-local deadline leaves room for the other source and final-check
# phases and guarantees that six variants cannot each consume a full read window.
DEFAULT_JSEARCH_SEARCH_BUDGET_SECONDS = 120.0
_MINIMUM_REQUEST_WINDOW_SECONDS = 1.0


class JSearchError(DiscoveryError):
    """Sanitized JSearch failure safe for operational metadata."""


class JSearchAuthenticationError(JSearchError):
    """The configured direct OpenWebNinja key was rejected."""


class JSearchPlanError(JSearchError):
    """The key is not entitled to call the direct JSearch endpoint."""


class JSearchRateLimitError(JSearchError):
    """The JSearch plan or account rate limit was reached."""


class JSearchUnavailableError(JSearchError):
    """Compatibility base for a transport or provider availability failure."""


class JSearchTimeoutError(JSearchUnavailableError):
    """The bounded JSearch request timed out."""


class JSearchConnectTimeoutError(JSearchTimeoutError):
    """The JSearch TCP, proxy CONNECT, or TLS connection phase timed out."""


class JSearchReadTimeoutError(JSearchTimeoutError):
    """JSearch did not return response data within the bounded read window."""


class JSearchWriteTimeoutError(JSearchTimeoutError):
    """The small JSearch GET request could not be written in time."""


class JSearchPoolTimeoutError(JSearchTimeoutError):
    """The local HTTP client could not acquire a connection in time."""


class JSearchDnsError(JSearchUnavailableError):
    """The JSearch hostname could not be resolved."""


class JSearchTlsError(JSearchUnavailableError):
    """The TLS connection to JSearch could not be verified or established."""


class JSearchProxyError(JSearchUnavailableError):
    """The configured network proxy could not reach JSearch."""


class JSearchConnectionError(JSearchUnavailableError):
    """A non-DNS JSearch connection or protocol error occurred."""


class JSearchProviderUnavailableError(JSearchUnavailableError):
    """JSearch itself returned an unavailable HTTP status or envelope."""


class JSearchRequestError(JSearchError):
    """JSearch rejected a request that contained no stored user payload."""


class JSearchResponseError(JSearchError):
    """JSearch returned an unexpected or unsuccessful response envelope."""


class OpenWebNinjaJSearchProvider:
    """Optional structured discovery source backed by JSearch search-v2."""

    name = "openwebninja-jsearch"
    attribution = "Structured job results via OpenWebNinja JSearch"
    attribution_url = "https://www.openwebninja.com/api/jsearch"
    endpoint = "https://api.openwebninja.com/jsearch/search-v2"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        connect_timeout_seconds: float = DEFAULT_JSEARCH_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds: float = DEFAULT_JSEARCH_READ_TIMEOUT_SECONDS,
        write_timeout_seconds: float = DEFAULT_JSEARCH_WRITE_TIMEOUT_SECONDS,
        pool_timeout_seconds: float = DEFAULT_JSEARCH_POOL_TIMEOUT_SECONDS,
        search_budget_seconds: float = DEFAULT_JSEARCH_SEARCH_BUDGET_SECONDS,
        max_requests: int = 3,
        max_transient_retries: int = 1,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        clean_key = api_key.strip()
        if not clean_key:
            raise ValueError("OpenWebNinja JSearch requires a non-empty API key")
        headers = {
            "Accept": "application/json",
            "X-API-Key": clean_key,
            "User-Agent": ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
        }
        # Create the environment-aware client only when the provider is first
        # called. Application startup must not fail merely because an optional
        # SOCKS proxy transport is configured without httpx's SOCKS extra.
        self.client = client
        self._owns_client = client is None
        self._client_headers = headers
        self._connect_timeout_seconds = max(0.1, float(connect_timeout_seconds))
        self._read_timeout_seconds = max(0.1, float(read_timeout_seconds))
        self._write_timeout_seconds = max(0.1, float(write_timeout_seconds))
        self._pool_timeout_seconds = max(0.1, float(pool_timeout_seconds))
        self.search_budget_seconds = max(1.0, float(search_budget_seconds))
        self._request_timeout = self._timeout_for_remaining(self.search_budget_seconds)
        if self.client is not None:
            self.client.headers.update(headers)
        self.max_requests = max(1, min(6, max_requests))
        self.max_transient_retries = max(0, min(2, max_transient_retries))
        self._sleep = sleeper
        self._clock = clock
        self.last_request_count = 0
        self._request_lock = Lock()

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        return len(self._search_queries(query)) * (self.max_transient_retries + 1)

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        searches = self._search_queries(query)
        deadline = self._clock() + self.search_budget_seconds
        self.last_request_count = 0
        jobs: list[DiscoveredJob] = []
        first_error: JSearchError | None = None

        # The Basic plan publishes an hourly allowance but no concurrent/RPS
        # entitlement.  Focused variants therefore run sequentially.  Besides
        # avoiding a burst of simultaneous calls, this lets an account-wide
        # auth, plan, or rate-limit failure stop before spending more quota.
        for search_text in searches:
            if self._remaining(deadline) < _MINIMUM_REQUEST_WINDOW_SECONDS:
                if jobs:
                    break
                raise JSearchTimeoutError(
                    "OpenWebNinja JSearch exceeded its provider search budget."
                )
            try:
                rows = self._request(search_text, query=query, deadline=deadline)
            except (JSearchAuthenticationError, JSearchPlanError, JSearchProxyError):
                raise
            except JSearchUnavailableError:
                # Host/transport availability is provider-wide, not specific to
                # a role synonym. Do not let six variants repeat the same long
                # timeout or continue after the mesh has stopped waiting. Keep
                # any usable rows already returned by an earlier variant.
                if jobs:
                    break
                raise
            except JSearchRateLimitError as exc:
                first_error = first_error or exc
                break
            except JSearchRequestError as exc:
                # A 4xx response rejects the shared request contract, not one
                # role synonym. Repeating variants only spends credits and
                # records copies of the same sanitized failure. Preserve any
                # usable rows returned before the provider-wide rejection.
                first_error = first_error or exc
                break
            except JSearchError as exc:
                first_error = first_error or exc
                continue
            for row in rows:
                parsed = self._parse(row)
                if parsed is not None:
                    jobs.append(parsed)

        if not jobs and first_error is not None:
            raise first_error
        return _deduplicate(jobs)[: query.limit]

    def _request(
        self,
        search_text: str,
        *,
        query: DiscoveryQuery,
        deadline: float,
    ) -> list[dict[str, object]]:
        response: httpx.Response | None = None
        for attempt in range(self.max_transient_retries + 1):
            remaining = self._remaining(deadline)
            if remaining < _MINIMUM_REQUEST_WINDOW_SECONDS:
                raise JSearchTimeoutError(
                    "OpenWebNinja JSearch exceeded its provider search budget."
                )
            with self._request_lock:
                self.last_request_count += 1
            try:
                response = self._active_client().get(
                    self.endpoint,
                    params=_request_params(query, search_text),
                    timeout=self._timeout_for_remaining(remaining),
                )
            except JSearchProxyError:
                raise
            except httpx.TransportError as exc:
                transport_error = _classify_transport_error(exc)
                # A read timeout may occur after the provider has accepted and
                # charged the request. Blindly replaying it doubles latency and
                # can spend another credit without improving availability.
                if isinstance(transport_error, JSearchReadTimeoutError):
                    raise transport_error from exc
                if attempt >= self.max_transient_retries or not self._retry_within_deadline(
                    _fallback_retry_delay(attempt), deadline
                ):
                    raise transport_error from exc
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES:
                retry_delay = _retry_delay(response, attempt)
                if attempt >= self.max_transient_retries or not self._retry_within_deadline(
                    retry_delay, deadline
                ):
                    if response.status_code == 429:
                        raise JSearchRateLimitError(
                            "OpenWebNinja JSearch reached its current plan rate limit."
                        )
                    raise JSearchProviderUnavailableError(
                        "OpenWebNinja JSearch returned a temporary server failure."
                    )
                continue
            break

        if response is None:
            raise JSearchConnectionError("OpenWebNinja JSearch could not be reached.")
        if response.status_code == 401:
            raise JSearchAuthenticationError(
                "OpenWebNinja JSearch rejected the configured API key."
            )
        if response.status_code in {402, 403}:
            raise JSearchPlanError(
                "The OpenWebNinja key is not entitled to the direct JSearch endpoint."
            )
        if 500 <= response.status_code < 600:
            raise JSearchProviderUnavailableError("OpenWebNinja JSearch returned a server failure.")
        if response.is_error:
            raise JSearchRequestError(
                f"OpenWebNinja JSearch rejected the request (HTTP {response.status_code})."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise JSearchResponseError(
                "OpenWebNinja JSearch returned an invalid JSON response."
            ) from exc
        if not isinstance(payload, dict):
            raise JSearchResponseError("JSearch response was not a JSON object.")
        return _response_rows(payload)

    def _active_client(self) -> httpx.Client:
        if self.client is not None:
            return self.client
        with self._request_lock:
            if self.client is None:
                try:
                    self.client = httpx.Client(
                        timeout=self._request_timeout,
                        follow_redirects=False,
                        trust_env=True,
                        headers=self._client_headers,
                    )
                except ImportError as exc:
                    raise JSearchProxyError(
                        "The configured proxy transport is unavailable."
                    ) from exc
                except ValueError as exc:
                    raise JSearchProxyError("The configured proxy transport is invalid.") from exc
                except (OSError, ssl.SSLError) as exc:
                    raise JSearchTlsError(
                        "The configured TLS certificate environment is invalid."
                    ) from exc
        return self.client

    def close(self) -> None:
        """Close a lazily-created client without taking ownership of injected clients."""

        if self._owns_client and self.client is not None:
            self.client.close()

    def _remaining(self, deadline: float) -> float:
        return max(0.0, deadline - self._clock())

    def _retry_within_deadline(self, delay: float, deadline: float) -> bool:
        remaining = self._remaining(deadline)
        if remaining - delay < _MINIMUM_REQUEST_WINDOW_SECONDS:
            return False
        self._sleep(min(delay, remaining))
        return self._remaining(deadline) >= _MINIMUM_REQUEST_WINDOW_SECONDS

    def _timeout_for_remaining(self, remaining: float) -> httpx.Timeout:
        """Return phase timeouts whose nominal sum fits the provider deadline.

        HTTPX applies phase timeouts independently rather than as a total wall
        clock. Reserving the short pool/connect/write windows before assigning
        the read window prevents a late retry from starting another full 90s
        read when the provider budget is nearly exhausted.
        """

        usable = max(0.4, remaining)
        pool = min(self._pool_timeout_seconds, usable * 0.1)
        connect = min(self._connect_timeout_seconds, usable * 0.25)
        write = min(self._write_timeout_seconds, usable * 0.1)
        read = min(
            self._read_timeout_seconds,
            max(0.1, usable - pool - connect - write),
        )
        return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)

    def _search_queries(self, query: DiscoveryQuery) -> list[str]:
        terms: list[str] = []
        candidates = [
            *query.desired_terms,
            *re.split(r"\s*[·;\n|]\s*", query.text),
        ]
        for candidate in candidates:
            clean = " ".join(str(candidate).replace("jobs", " ").split())[:120]
            if len(clean) < 2:
                continue
            focused = _role_search_term(clean)
            if focused.casefold() not in {item.casefold() for item in terms}:
                terms.append(focused)
            if len(terms) >= self.max_requests:
                break
        if not terms:
            terms = [" ".join(query.text.split())[:120]]

        location = ""
        if query.remote_only:
            location = " remote"
        elif query.location.strip() and not query.worldwide:
            location = f" in {' '.join(query.location.split())[:100]}"
        return [f"{term} jobs{location}".strip() for term in terms]

    @staticmethod
    def _parse(row: dict[str, object]) -> DiscoveredJob | None:
        title = _plain_text(row.get("job_title"))[:500]
        source_url = _apply_url(row)
        if not title or source_url is None:
            return None
        company = _plain_text(row.get("employer_name"))
        if not company:
            company = _plain_text(row.get("job_publisher"))
        if not company:
            company = (urlsplit(source_url).hostname or "Employer").removeprefix("www.")

        location = _plain_text(row.get("job_location"))
        if not location:
            location = _join_distinct(
                row.get("job_city"),
                row.get("job_state"),
                row.get("job_country"),
            )
        remote = bool(row.get("job_is_remote"))
        if not location:
            location = "Remote" if remote else "Location not stated"

        tags = ["JSearch"]
        for value in _list_values(
            row.get("job_employment_types") or row.get("job_employment_type")
        ):
            clean = _plain_text(value)
            if clean and clean.casefold() not in {item.casefold() for item in tags}:
                tags.append(clean[:100])
        publisher = _plain_text(row.get("job_publisher"))
        if publisher and publisher.casefold() != company.casefold():
            tags.append(f"Published via {publisher}"[:100])

        external_id = _plain_text(row.get("job_id")) or source_url
        try:
            return DiscoveredJob(
                provider=OpenWebNinjaJSearchProvider.name,
                external_id=external_id[:500],
                title=title,
                company=company[:500],
                location=location[:500],
                remote=remote,
                tags=tags[:12],
                summary=_plain_text(row.get("job_description"))[:1_500],
                source_url=source_url,
                published_at=_posted_at(row),
            )
        except ValueError:
            # Malformed third-party rows fail closed without losing valid rows
            # returned by the same provider request.
            return None


def _apply_url(row: dict[str, object]) -> str | None:
    options = row.get("apply_options")
    direct: list[str] = []
    other: list[str] = []
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            value = str(option.get("apply_link") or option.get("link") or "").strip()
            if not _is_http_url(value):
                continue
            (direct if option.get("is_direct") else other).append(value)
    candidates = [
        *direct,
        str(row.get("job_apply_link") or "").strip(),
        *other,
    ]
    return next((value for value in candidates if _is_http_url(value)), None)


def _response_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    """Read documented search-v2 jobs without retaining response content.

    OpenWebNinja's current direct API wraps the list as ``data.jobs`` and adds
    pagination metadata beside it.  Earlier responses exposed ``data`` as the
    list itself.  A top-level ``jobs`` list is accepted as a conservative
    compatibility shape, but arbitrary nested lists are deliberately ignored.
    """

    failure = _response_failure(payload)
    if failure is not None:
        raise failure

    status = payload.get("status")
    if status not in (None, ""):
        normalized_status = _normalized_code(status)
        if normalized_status not in _SUCCESS_ENVELOPE_STATUSES:
            raise JSearchResponseError("JSearch returned an unrecognized response status.")

    data = payload.get("data")
    rows: object
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and "jobs" in data:
        rows = data.get("jobs")
    elif "jobs" in payload:
        rows = payload.get("jobs")
    else:
        raise JSearchResponseError("JSearch response did not contain a supported jobs collection.")

    if not isinstance(rows, list):
        raise JSearchResponseError("JSearch jobs collection was not a list.")
    if not all(isinstance(row, dict) for row in rows):
        raise JSearchResponseError("JSearch response contained an invalid result row.")
    return [dict(row) for row in rows]


def _response_failure(payload: dict[str, object]) -> JSearchError | None:
    """Classify only bounded machine indicators from a success-status body.

    Some gateways express account failures in a JSON envelope while returning
    HTTP 200.  The response text, query, URL and key are never copied into the
    resulting exception.  Unknown error envelopes remain a generic schema
    failure rather than guessing from free-form provider messages.
    """

    containers = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data)
    error = payload.get("error")
    if isinstance(error, dict):
        containers.append(error)

    codes: set[str] = set()
    for container in containers:
        for key in ("code", "error_code", "http_status", "status_code"):
            value = container.get(key)
            if value not in (None, ""):
                codes.add(_normalized_code(value))
    status = payload.get("status")
    if status not in (None, ""):
        codes.add(_normalized_code(status))
    if error not in (None, "") and not isinstance(error, (dict, list)):
        codes.add(_normalized_code(error))

    if codes.intersection(_AUTHENTICATION_ERROR_CODES):
        return JSearchAuthenticationError("OpenWebNinja JSearch rejected the configured API key.")
    if codes.intersection(_PLAN_ERROR_CODES):
        return JSearchPlanError(
            "The OpenWebNinja key is not entitled to the direct JSearch endpoint."
        )
    if codes.intersection(_RATE_LIMIT_ERROR_CODES):
        return JSearchRateLimitError("OpenWebNinja JSearch reached its current plan rate limit.")
    if codes.intersection(_UNAVAILABLE_ERROR_CODES):
        return JSearchProviderUnavailableError(
            "OpenWebNinja JSearch returned an unavailable response envelope."
        )

    normalized_status = _normalized_code(status) if status not in (None, "") else ""
    has_error = error not in (None, "", False, {}, [])
    if normalized_status in _FAILURE_ENVELOPE_STATUSES or has_error:
        return JSearchResponseError("JSearch returned an unsuccessful response envelope.")
    return None


def _normalized_code(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


def _classify_transport_error(error: httpx.TransportError) -> JSearchUnavailableError:
    """Map transport exceptions to fixed, secret-safe operational categories.

    httpx preserves low-level causes when it maps socket and TLS exceptions.
    Inspecting their types lets the explicit diagnostic distinguish a DNS or
    certificate problem without ever copying exception text, request URLs, or
    proxy details into persisted provider metadata.
    """

    if isinstance(error, httpx.ConnectTimeout):
        return JSearchConnectTimeoutError("OpenWebNinja JSearch connection timed out.")
    if isinstance(error, httpx.ReadTimeout):
        return JSearchReadTimeoutError("OpenWebNinja JSearch response timed out.")
    if isinstance(error, httpx.WriteTimeout):
        return JSearchWriteTimeoutError("OpenWebNinja JSearch request write timed out.")
    if isinstance(error, httpx.PoolTimeout):
        return JSearchPoolTimeoutError("OpenWebNinja JSearch connection pool timed out.")
    if isinstance(error, httpx.TimeoutException):
        return JSearchTimeoutError("OpenWebNinja JSearch timed out.")
    if isinstance(error, httpx.ProxyError):
        return JSearchProxyError("The configured proxy could not reach OpenWebNinja JSearch.")
    if _exception_chain_contains(error, ssl.SSLError):
        return JSearchTlsError("The OpenWebNinja JSearch TLS connection failed.")
    if _exception_chain_contains(error, socket.gaierror):
        return JSearchDnsError("The OpenWebNinja JSearch hostname could not be resolved.")
    return JSearchConnectionError("The OpenWebNinja JSearch connection failed.")


def _exception_chain_contains(error: BaseException, expected: type[BaseException]) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, expected):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _request_params(query: DiscoveryQuery, search_text: str) -> dict[str, object]:
    params: dict[str, object] = {
        "query": search_text,
        # Keep search-v2 at its canonical query-only shape. Legacy
        # ``num_pages`` and the optional ``fields`` projection proved brittle
        # against the cursor-based live endpoint and produced HTTP 4xx.
    }
    if query.remote_only:
        params["work_from_home"] = "true"
    if query.worldwide or not query.location.strip():
        return params

    clean_location = query.location.strip()
    country_code = _country_code_for_location(clean_location)
    if country_code:
        params["country"] = country_code.casefold()
        language = _MARKET_LANGUAGES.get(country_code)
        if language:
            params["language"] = language
    return params


def _country_code_for_location(location: str) -> str:
    """Resolve both canonical Compass origins and human compound labels.

    A saved origin can legitimately be rendered as ``Frankfurt am Main,
    Germany``.  Treating that complete label as one city used to lose the
    country/language parameters even though both comma-separated parts were
    individually unambiguous.
    """

    clean = " ".join(location.split())
    candidates = [clean]
    candidates.extend(
        part.strip()
        for part in re.split(r"[,;|]", clean)
        if part.strip() and part.strip().casefold() != clean.casefold()
    )
    for candidate in candidates:
        country_code = country_code_for_label(candidate)
        if country_code:
            return country_code.upper()
    for candidate in candidates:
        resolved = _POSTAL_INDEX.resolve(candidate) or _PLACE_INDEX.resolve_for_explore(candidate)
        if resolved is not None:
            return resolved.country_code.upper()
    return ""


def _role_search_term(value: str) -> str:
    """Turn Compass concepts into title-like JSearch phrases.

    JSearch's own examples search for occupations (``developer in berlin``).
    Compass role families are often noun concepts such as ``embedded software``
    or ``test automation``.  These bounded, deterministic expansions improve
    recall without sending more requests or inventing unrelated skills.
    """

    clean = " ".join(value.split())[:120]
    folded = clean.casefold()
    tokens = set(re.findall(r"[^\W\d_][\w+#.-]*", folded, flags=re.UNICODE))
    if tokens.intersection(_ROLE_MARKERS):
        return clean
    if "embedded" in tokens and "software" in tokens:
        return "embedded software engineer"
    if "fpga" in tokens or "vhdl" in tokens:
        return "FPGA engineer"
    if "test" in tokens or "testing" in tokens or "qa" in tokens:
        return "test automation engineer" if "automation" in tokens else "QA engineer"
    if any(token.startswith("prototyp") for token in tokens):
        return "prototyping engineer"
    if {"ux", "ui"}.intersection(tokens):
        return "UX UI designer"
    if "product" in tokens and {"management", "manager"}.intersection(tokens):
        return "product manager"
    if "software" in tokens:
        return "software developer"
    if "automation" in tokens:
        return "automation engineer"
    if "engineering" in tokens:
        return re.sub(r"(?i)\bengineering\b", "engineer", clean)
    if "development" in tokens:
        return re.sub(r"(?i)\bdevelopment\b", "developer", clean)
    if len(tokens) == 1 and next(iter(tokens), "") in {
        "c",
        "c++",
        "cpp",
        "java",
        "javascript",
        "python",
        "rust",
        "typescript",
    }:
        return f"{clean} developer"
    return clean


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Honor standard Retry-After without allowing an unbounded provider pause."""

    value = response.headers.get("Retry-After", "").strip()
    if value:
        try:
            return min(10.0, max(0.0, float(value)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                retry_at = None
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
                return min(10.0, max(0.0, seconds))
    return _fallback_retry_delay(attempt)


def _fallback_retry_delay(attempt: int) -> float:
    return min(2.0, 0.5 * (2**attempt))


def _posted_at(row: dict[str, object]) -> datetime | None:
    value = row.get("job_posted_at_datetime_utc")
    if value not in (None, ""):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    timestamp = row.get("job_posted_at_timestamp")
    try:
        return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _plain_text(value: object) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(without_tags).split())


def _join_distinct(*values: object) -> str:
    result: list[str] = []
    for value in values:
        clean = _plain_text(value)
        if clean and clean.casefold() not in {item.casefold() for item in result}:
            result.append(clean)
    return ", ".join(result)


def _list_values(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return [] if value in (None, "") else [value]


def _deduplicate(jobs: list[DiscoveredJob]) -> list[DiscoveredJob]:
    unique: dict[str, DiscoveredJob] = {}
    for job in jobs:
        unique.setdefault(str(job.source_url).casefold().rstrip("/"), job)
    return list(unique.values())
