"""Legal, source-attributed job discovery for the Explore workflow."""

from __future__ import annotations

import html
import math
import re
import time
import unicodedata
from concurrent.futures import wait
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from threading import Lock
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import AnyHttpUrl, Field

from .brave_search import (
    BRAVE_WEB_SEARCH_ENDPOINT,
    BraveSearchError,
    BraveSearchResponseError,
    BraveSearchUnavailableError,
    request_brave_web_page,
    request_brave_web_results,
)
from .concurrency import DaemonThreadPoolExecutor
from .geography import (
    OfflineGermanPostalCodeIndex,
    OfflinePlaceIndex,
    ResolvedPlace,
    ResolvedPostalCode,
    country_continent_code,
    country_search_terms,
    straight_line_distance_km,
)
from .posting_date import classify_posting_date, posting_date_score_adjustment
from .profile import CandidateProfile, RequirementLevel, StrictModel
from .profile_mobility import mobility_widget_preferences
from .url_ingestion import PublicUrlFetcher, UrlIngestionError


_PLACE_INDEX = OfflinePlaceIndex()
_POSTAL_INDEX = OfflineGermanPostalCodeIndex()
MAX_PORTAL_SEARCH_SCOPES = 5


# Web-search providers can return category pages that merely contain job-search
# keywords.  Keep this evidence-based policy narrow: employer career pages are
# allowed, while sources that have repeatedly failed the single-vacancy contract
# are rejected before they can enter an Explore snapshot.
WEB_DISCOVERY_EXCLUDED_DOMAINS = frozenset(
    {
        "absolventa.de",
        "glassdoor.com",
        "indeed.com",
        "linkedin.com",
        "stepstone.de",
        "xing.com",
    }
)

# Hosts used only for suspended accounts, domain parking, or resale are never
# a vacancy source.  Search indexes can retain the original employer-looking
# URL after it starts redirecting to one of these destinations, so the bounded
# availability pass checks the final URL as well as the submitted URL.
WEB_DISCOVERY_ERROR_DESTINATION_DOMAINS = frozenset(
    {
        "bodis.com",
        "hugedomains.com",
        "parkingcrew.net",
        "sedoparking.com",
        "suspended-domain.net",
    }
)

# These sources return web-search result pages and therefore share the same
# source-page policy. The legacy ``exa-fallback`` storage key remains for saved
# snapshot compatibility; it no longer gives Exa an implicit ranking advantage.
WEB_DISCOVERY_PROVIDER_NAMES = frozenset({"exa-fallback", "you-web", "brave-web"})

# Published employer records have already passed the product's own approval and
# publication boundary. Their local public page must not be downgraded merely
# because the generic URL preflight quite correctly refuses to fetch a loopback
# address in a local installation.
TRUSTED_PUBLISHED_PROVIDER_NAMES = frozenset({"betteroption-posted"})

# Brave accepts a bounded list of interface markets. Use the documented market
# language where one exists and fall back to its stable English/US contract for
# origins outside that list. This affects result localization only; the
# independently generated German/English role queries remain unchanged.
_BRAVE_MARKET_LANGUAGES: dict[str, tuple[str, str]] = {
    "AR": ("es", "es-AR"),
    "AT": ("de", "de-AT"),
    "AU": ("en", "en-AU"),
    "BE": ("nl", "nl-BE"),
    "BR": ("pt-br", "pt-BR"),
    "CA": ("en", "en-CA"),
    "CH": ("de", "de-CH"),
    "CL": ("es", "es-CL"),
    "CN": ("zh-hans", "zh-CN"),
    "DE": ("de", "de-DE"),
    "DK": ("da", "da-DK"),
    "ES": ("es", "es-ES"),
    "FI": ("fi", "fi-FI"),
    "FR": ("fr", "fr-FR"),
    "GB": ("en", "en-GB"),
    "GR": ("el", "el-GR"),
    "HK": ("zh-hant", "zh-HK"),
    "ID": ("id", "id-ID"),
    "IN": ("en", "en-IN"),
    "IT": ("it", "it-IT"),
    "JP": ("jp", "ja-JP"),
    "KR": ("ko", "ko-KR"),
    "MX": ("es", "es-MX"),
    "MY": ("en", "en-MY"),
    "NL": ("nl", "nl-NL"),
    "NO": ("nb", "no-NO"),
    "NZ": ("en", "en-NZ"),
    "PH": ("en", "en-PH"),
    "PL": ("pl", "pl-PL"),
    "RU": ("ru", "ru-RU"),
    "SE": ("sv", "sv-SE"),
    "TR": ("tr", "tr-TR"),
    "TW": ("zh-hant", "zh-TW"),
    "US": ("en", "en-US"),
    "ZA": ("en", "en-ZA"),
}

_GENERIC_JOB_PAGE_LEAVES = frozenset(
    {
        "career",
        "careers",
        "job",
        "jobs",
        "job-search",
        "jobsearch",
        "openings",
        "open-positions",
        "job-openings",
        "join-us",
        "position",
        "positions",
        "role",
        "roles",
        "search",
        "search-jobs",
        "stellen",
        "stellenangebote",
        "vacancies",
        "vacancy",
    }
)
_NON_VACANCY_PATH_PARTS = frozenset(
    {
        "article",
        "articles",
        "blog",
        "blogs",
        "career-advice",
        "categories",
        "category",
        "guide",
        "guides",
        "insights",
        "job-search",
        "jobsearch",
        "news",
        "resources",
        "search",
        "search-jobs",
    }
)
_JOB_IDENTIFIER_QUERY_KEYS = frozenset(
    {
        "career_job_req_id",
        "gh_jid",
        "job",
        "jobid",
        "job_id",
        "jk",
        "jid",
        "postingid",
        "positionid",
        "reqid",
        "requisitionid",
        "vacancy_id",
        "vacancyid",
    }
)
_TRACKING_QUERY_KEYS = frozenset(
    {
        "campaign",
        "fbclid",
        "from",
        "gad_source",
        "gclid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref",
        "referrer",
        "source",
        "trackingid",
        "trk",
    }
)


def _web_discovery_has_explicit_job_identifier(
    parsed,
    path_parts: list[str],
) -> bool:
    """Recognise explicit identifiers without treating a generic ATS page as a job."""

    query_keys = {key.casefold() for key, _ in _safe_query_pairs(parsed.query)}
    if query_keys.intersection(_JOB_IDENTIFIER_QUERY_KEYS):
        return True

    host = (parsed.hostname or "").casefold().rstrip(".")
    if host == "icims.com" or host.endswith(".icims.com"):
        return any(
            part == "jobs"
            and index + 1 < len(path_parts)
            and bool(re.fullmatch(r"\d+", path_parts[index + 1]))
            for index, part in enumerate(path_parts)
        )
    return False


def web_discovery_source_is_excluded(value: str) -> bool:
    """Return whether a URL belongs to an explicitly incompatible web source."""

    try:
        host = (urlsplit(value).hostname or "").casefold().rstrip(".")
    except ValueError:
        return True
    return any(
        host == domain or host.endswith(f".{domain}") for domain in WEB_DISCOVERY_EXCLUDED_DOMAINS
    )


def web_discovery_url_is_error_landing(value: str) -> bool:
    """Reject explicit error destinations which can still return HTTP 200."""

    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold().rstrip(".")
        path_parts = [part.casefold() for part in parsed.path.split("/") if part]
    except ValueError:
        return True
    if any(
        host == domain or host.endswith(f".{domain}")
        for domain in WEB_DISCOVERY_ERROR_DESTINATION_DOMAINS
    ):
        return True
    return bool(path_parts) and path_parts[-1] in {
        "error",
        "404",
        "not-found",
        "page-not-found",
        "notfound",
        "searchjobs",
        "search-jobs",
        "job-search",
        "jobsearch",
    }


def web_discovery_document_is_error_landing(final_url: str, text: str) -> bool:
    """Recognise a small set of unambiguous HTTP-200 error/parking pages.

    This deliberately avoids fuzzy sentiment or security classification.  A
    page is rejected only when its final destination is known to be non-job
    infrastructure or its visible text carries an explicit missing/suspended
    page statement in one of the common Explore markets.
    """

    if web_discovery_url_is_error_landing(final_url):
        return True
    try:
        parsed = urlsplit(final_url)
        final_path_parts = [part.casefold() for part in parsed.path.split("/") if part]
    except ValueError:
        return True
    if any(part in _NON_VACANCY_PATH_PARTS for part in final_path_parts):
        return True
    if (
        final_path_parts
        and final_path_parts[-1] in _GENERIC_JOB_PAGE_LEAVES
        and not _web_discovery_has_explicit_job_identifier(parsed, final_path_parts)
    ):
        return True
    material = " ".join(text.casefold().split())[:20_000]
    if any(
        marker in material
        for marker in (
            "404 page not found",
            "404 not found",
            "account has been suspended",
            "buy this domain",
            "deceptive site ahead",
            "diese url existiert nicht",
            "diese seite wurde nicht gefunden",
            "domain has been suspended",
            "domain is for sale",
            "domain is suspended",
            "job is no longer available",
            "job page not found",
            "job posting has expired",
            "job posting is no longer available",
            "job wurde entfernt",
            "phishing site",
            "page does not exist",
            "page has been removed",
            "page was not found",
            "position has been filled",
            "seite existiert nicht",
            "seite wurde nicht gefunden",
            "the page you requested could not be found",
            "this domain is parked",
            "this page does not exist",
            "this position is no longer available",
            "this url does not exist",
            "website is for sale",
        )
    ):
        return True
    return bool(
        re.search(
            r"\b(?:top|best)\s+\d{1,3}\b.{0,100}\b(?:job\s+boards?|job\s+sites?)\b",
            material[:4_000],
        )
        or re.search(
            r"\b\d{1,3}\s+(?:best|top)\b.{0,100}\b(?:job\s+boards?|job\s+sites?)\b",
            material[:4_000],
        )
    )


def web_discovery_document_is_individual_job(text: str) -> bool:
    """Require source-page evidence of one vacancy before showing a web hit.

    The check is intentionally broad and multilingual, but it still requires a
    vacancy/application signal plus normal advertisement structure. Search and
    editorial pages can therefore be reachable without being admitted.
    """

    material = " ".join(text.casefold().split())[:40_000]
    if all(marker in material for marker in ("title:", "company:", "description:")):
        return True
    vacancy_signal = any(
        marker in material
        for marker in (
            "apply for this",
            "apply now",
            "application deadline",
            "bewerben",
            "bewerbung",
            "candidatura",
            "join our team",
            "jetzt bewerben",
            "postuler",
            "solicitud",
            "solliciteren",
            "submit your application",
            "we are hiring",
            "we are looking for",
            "wir suchen",
        )
    )
    section_signal = any(
        marker in material
        for marker in (
            "about the role",
            "anforderungen",
            "aufgaben",
            "description du poste",
            "employment type",
            "funciones",
            "ihre aufgaben",
            "qualifications",
            "requisitos",
            "requisiti",
            "responsabilities",
            "responsabilità",
            "responsibilities",
            "tätigkeiten",
            "what you will do",
            "what you'll do",
            "your profile",
        )
    )
    return vacancy_signal and section_signal


def web_discovery_title_is_error_landing(value: str) -> bool:
    title = " ".join(value.casefold().split())
    if title in {"job search", "search jobs", "search vacancies", "career search"}:
        return True
    return bool(re.match(r"^(?:error|page not found|access denied)(?:\b|\s*[|–—-])", title))


def web_discovery_title_is_generic_or_editorial(value: str) -> bool:
    """Reject category/search/editorial titles instead of individual vacancies."""

    title = " ".join(value.casefold().split()).strip(" -|–—")
    if not title:
        return True
    if re.search(
        r"\b(?:top|best)\s+\d{1,3}\b.*\b(?:job\s+boards?|job\s+sites?|career\s+sites?)\b",
        title,
    ) or re.search(
        r"\b\d{1,3}\s+(?:best|top)\b.*\b(?:job\s+boards?|job\s+sites?|career\s+sites?)\b",
        title,
    ):
        return True
    if re.search(
        r"\b(?:how to|salary guide|career advice|job search tips|find a job)\b",
        title,
    ):
        return True
    return bool(
        re.fullmatch(
            r"(?:find |search )?(?:all |open )?(?:remote )?"
            r"(?:jobs?|careers?|vacancies|open positions|stellenangebote)"
            r"(?: in [^|]+)?",
            title,
        )
        or re.fullmatch(r".+\bjobs(?: in [^|]+)?", title)
    )


def discovery_result_is_plausible_individual_job(
    value: str,
    title: str,
    summary: str = "",
) -> bool:
    """Return whether a candidate URL plausibly identifies one job posting.

    This provider-independent structural gate does not claim that a vacancy is
    open or that BetterOption can fetch it.  It only prevents obvious roots,
    search/category pages and editorial pages from entering ranking or a saved
    Explore snapshot.  Raw web-search candidates receive the additional domain
    policy in :func:`web_discovery_result_is_plausible_job` below.
    """

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme != "https" or not host:
        return False
    if web_discovery_url_is_error_landing(value):
        return False
    if web_discovery_title_is_error_landing(title) or web_discovery_title_is_generic_or_editorial(
        title
    ):
        return False

    path_parts = [part.casefold() for part in parsed.path.split("/") if part]
    if any(part in _NON_VACANCY_PATH_PARTS for part in path_parts):
        return False
    has_explicit_identifier = _web_discovery_has_explicit_job_identifier(parsed, path_parts)
    if path_parts and path_parts[-1] in _GENERIC_JOB_PAGE_LEAVES and not has_explicit_identifier:
        return False
    if has_explicit_identifier:
        return True

    # Known public ATS URLs encode a board plus a posting identifier/slug.
    ats_host = any(
        marker in host
        for marker in (
            "ashbyhq.com",
            "greenhouse.io",
            "icims.com",
            "lever.co",
            "myworkdayjobs.com",
            "personio.",
            "smartrecruiters.com",
            "successfactors.",
            "workable.com",
        )
    )
    if ats_host and len(path_parts) >= 2 and path_parts[-1] not in _GENERIC_JOB_PAGE_LEAVES:
        return True

    marker_positions = [
        index
        for index, part in enumerate(path_parts)
        if part in _GENERIC_JOB_PAGE_LEAVES
        or part in {"job-detail", "job-details", "jobdetail", "position-details"}
        or re.fullmatch(r"(?:job|jobs|position|vacancy|stelle|stellenangebot)-?\d+", part)
    ]
    if marker_positions and any(index < len(path_parts) - 1 for index in marker_positions):
        leaf = path_parts[-1]
        if leaf not in _GENERIC_JOB_PAGE_LEAVES and (len(leaf) >= 3 or leaf.isdigit()):
            return True

    # Some employer sites expose a descriptive vacancy slug without a /jobs/
    # segment or career-specific hostname. A non-root, non-generic path plus
    # explicit role language is enough to enter the bounded page preflight;
    # it still does not claim that the source is open or importable.
    material = f"{title} {summary}".casefold()
    role_language = bool(
        re.search(
            r"\b(?:administrator|analyst|architect|assistant|consultant|designer|"
            r"developer|director|engineer|entwickler|fachkraft|manager|mechanic|"
            r"operator|praktikant|researcher|specialist|technician|werkstudent)\b",
            material,
        )
    )
    return bool(path_parts and len(path_parts[-1]) >= 5 and role_language)


def web_discovery_result_is_plausible_job(
    value: str,
    title: str,
    summary: str = "",
) -> bool:
    """Apply the stricter raw-web policy on top of the universal URL gate."""

    return not web_discovery_source_is_excluded(
        value
    ) and discovery_result_is_plausible_individual_job(value, title, summary)


def _safe_query_pairs(value: str) -> list[tuple[str, str]]:
    """Parse query keys without allowing malformed search results to escape."""

    try:
        return parse_qsl(value, keep_blank_values=True, max_num_fields=50)
    except ValueError:
        return []


class DiscoveryError(RuntimeError):
    """Raised when discovery cannot return trustworthy results."""


class SeniorityBand(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    MANAGER = "manager"


class SourceReadiness(StrEnum):
    """How safely an Explore discovery can enter the URL-import workflow."""

    READY = "ready"
    PROVIDER_LISTED = "provider_listed"
    MANUAL_REQUIRED = "manual_required"


class DiscoveryQuery(StrictModel):
    text: str = Field(min_length=2, max_length=400)
    location: str = Field(default="", max_length=200)
    remote_only: bool = False
    onsite_only: bool = False
    include_remote_jobs: bool = True
    remote_preferred: bool = False
    # Explore can surface a broader research set within the source mesh's shared
    # bounded provider budget. Individual providers, bounded
    # availability checks, deduplication, and evidence-based ranking still run
    # before this presentation limit is applied.
    limit: int = Field(default=300, ge=1, le=300)
    desired_terms: list[str] = Field(default_factory=list, max_length=30)
    excluded_terms: list[str] = Field(default_factory=list, max_length=30)
    seniority_targets: list[SeniorityBand] = Field(default_factory=list, max_length=6)
    regional_target: int = Field(default=0, ge=0, le=180)
    regional_radius_km: float = Field(default=150, ge=10, le=300)
    worldwide: bool = False
    include_custom_portals: bool = True
    preferred_portals: list[str] = Field(default_factory=list, max_length=10)
    # Kept for stored v0.7.1g searches. New searches preserve each portal's
    # normalized path so a saved locale is not widened to the whole host.
    preferred_domains: list[str] = Field(default_factory=list, max_length=10)

    @property
    def work_arrangement_label(self) -> str:
        if self.remote_only:
            return "Remote roles only"
        if self.onsite_only:
            return "On-site roles; explicit remote roles are excluded"
        if not self.include_remote_jobs:
            return "Remote-only roles are hidden"
        if self.remote_preferred:
            return "Remote roles are preferred; nearby roles remain visible"
        return "Remote-only roles are included after reachable local roles"


def _portal_scopes(query: DiscoveryQuery) -> list[tuple[str, str]]:
    scopes: list[tuple[str, str]] = []
    for raw in [*query.preferred_portals, *query.preferred_domains]:
        value = raw.strip()
        if not value:
            continue
        parsed = urlsplit(value if "://" in value else f"https://{value}")
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        path = parsed.path.rstrip("/")
        if host and (host, path) not in scopes:
            scopes.append((host, path))
    return scopes


def web_discovery_matches_portal(value: str, query: DiscoveryQuery) -> bool:
    """Match a result to a saved host and, when supplied, its path/locale."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return any(
        host == saved_host and (not saved_path or path.casefold().startswith(saved_path.casefold()))
        for saved_host, saved_path in _portal_scopes(query)
    )


class DiscoveredJob(StrictModel):
    provider: str
    # ``provider`` remains the source whose richer evidence won canonical-URL
    # deduplication.  This list retains every source which returned that same
    # canonical URL so local presentation filters do not hide corroborated
    # results merely because their primary evidence came from another source.
    # Old snapshots omit the field and are interpreted through the property
    # below as having exactly their legacy primary provider.
    source_providers: list[str] = Field(default_factory=list, max_length=20)
    source_readiness: SourceReadiness = SourceReadiness.PROVIDER_LISTED
    external_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(min_length=1, max_length=500)
    location: str = Field(default="Location not stated", max_length=500)
    remote: bool = False
    tags: list[str] = Field(default_factory=list)
    summary: str = Field(default="", max_length=1_500)
    source_url: AnyHttpUrl
    published_at: datetime | None = None
    distance_km: float | None = Field(default=None, ge=0)
    distance_relevance: int | None = Field(default=None, ge=0, le=100)
    keyword_relevance: int | None = Field(default=None, ge=0, le=100)
    seniority_relevance: int | None = Field(default=None, ge=0, le=100)
    compass_relevance: int | None = Field(default=None, ge=0, le=100)
    seniority_note: str | None = Field(default=None, max_length=500)
    seniority_conflict: bool = False
    exclusion_signals: list[str] = Field(default_factory=list)
    search_score: int | None = Field(default=None, ge=0, le=100)

    @property
    def effective_source_providers(self) -> tuple[str, ...]:
        """Return stable provider provenance for both new and legacy rows."""

        providers: list[str] = []
        seen: set[str] = set()
        for candidate in [*self.source_providers, self.provider]:
            clean = candidate.strip()
            folded = clean.casefold()
            if not clean or folded in seen:
                continue
            seen.add(folded)
            providers.append(clean)
        return tuple(providers)


def _raw_web_only(job: DiscoveredJob) -> bool:
    """Return whether every source supporting a result is an unverified web search."""

    return all(
        provider in WEB_DISCOVERY_PROVIDER_NAMES for provider in job.effective_source_providers
    )


def _trusted_published_source(job: DiscoveredJob) -> bool:
    """Return whether an approved first-party publication supports the result."""

    return any(
        provider in TRUSTED_PUBLISHED_PROVIDER_NAMES for provider in job.effective_source_providers
    )


class DiscoveryAttribution(StrictModel):
    label: str
    url: AnyHttpUrl


class JobDiscoveryProvider(Protocol):
    name: str
    attribution: str
    attribution_url: str

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        """Return public jobs with inspectable source URLs."""


class DiscoveryAvailabilityFilter:
    """Verify raw web hits and annotate structured-source import readiness.

    Direct ATS and job-feed APIs already expose their active corpus. Web-search
    fallbacks can contain stale, parked, editorial, or deceptive index entries,
    so those URLs receive a bounded, robots-aware source check. A blocked,
    unchecked, timed-out, redirected-to-error, or otherwise unverified web hit
    is omitted instead of being presented as a candidate vacancy. Structured
    sources remain usable discovery evidence, but a bounded preflight labels a
    successfully fetched individual page ``ready``, a checked but unusable page
    ``manual_required``, and an unchecked row only ``provider_listed``. The
    latter must never be presented as verified reachable.
    """

    WEB_DISCOVERY_PROVIDERS = WEB_DISCOVERY_PROVIDER_NAMES

    def __init__(
        self,
        *,
        fetcher: PublicUrlFetcher | None = None,
        max_workers: int = 10,
        cache_ttl: timedelta = timedelta(minutes=15),
        maximum_checks: int = 80,
        maximum_checks_per_host: int = 5,
        total_timeout_seconds: float = 35.0,
    ) -> None:
        self.fetcher = fetcher or PublicUrlFetcher(maximum_bytes=750_000)
        self.max_workers = max(1, min(16, max_workers))
        self.cache_ttl = cache_ttl
        self.maximum_checks = max(0, maximum_checks)
        self.maximum_checks_per_host = max(1, maximum_checks_per_host)
        self.total_timeout_seconds = max(0.1, total_timeout_seconds)
        self._cache: dict[str, tuple[datetime, bool]] = {}
        self._host_locks: dict[str, Lock] = {}
        self._cache_lock = Lock()

    def keep_open_or_unknown(
        self,
        jobs: Iterable[DiscoveredJob],
        *,
        timeout_seconds: float | None = None,
        check_control: Callable[[], None] | None = None,
    ) -> list[DiscoveredJob]:
        candidates = list(jobs)
        if self.maximum_checks <= 0 or (timeout_seconds is not None and timeout_seconds <= 0):
            return [
                job.model_copy(
                    update={
                        "source_readiness": (
                            SourceReadiness.READY
                            if _trusted_published_source(job)
                            else SourceReadiness.PROVIDER_LISTED
                        )
                    }
                )
                for job in candidates
                if not _raw_web_only(job)
            ]
        checks: dict[str, DiscoveredJob] = {}
        host_counts: dict[str, int] = {}
        check_order = sorted(
            candidates,
            key=lambda job: (
                not _raw_web_only(job),
                "Saved employer portal" not in job.tags,
            ),
        )
        for job in check_order:
            if _trusted_published_source(job):
                continue
            url = str(job.source_url)
            if url in checks:
                continue
            host = (urlsplit(url).hostname or url).casefold()
            if host_counts.get(host, 0) >= self.maximum_checks_per_host:
                continue
            checks[url] = job
            host_counts[host] = host_counts.get(host, 0) + 1
            if len(checks) >= self.maximum_checks:
                break
        if not checks:
            return [
                job.model_copy(
                    update={
                        "source_readiness": (
                            SourceReadiness.READY
                            if _trusted_published_source(job)
                            else SourceReadiness.PROVIDER_LISTED
                        )
                    }
                )
                for job in candidates
                if not _raw_web_only(job)
            ]

        verified_open_urls: set[str] = set()
        checked_urls: set[str] = set()
        executor = DaemonThreadPoolExecutor(
            max_workers=min(self.max_workers, len(checks)),
            thread_name_prefix="source-availability",
        )
        futures = {executor.submit(self._is_verified_open, url): url for url in checks}
        pending = set(futures)
        completed = set()
        deadline = time.monotonic() + min(
            self.total_timeout_seconds,
            timeout_seconds if timeout_seconds is not None else self.total_timeout_seconds,
        )
        try:
            while pending:
                if check_control is not None:
                    check_control()
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    break
                batch, pending = wait(pending, timeout=min(0.25, remaining))
                completed.update(batch)
            for future in completed:
                url = futures[future]
                checked_urls.add(url)
                try:
                    if future.result():
                        verified_open_urls.add(url)
                except Exception:  # pragma: no cover - unverified web hits fail closed
                    continue
            for future in pending:
                future.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        kept: list[DiscoveredJob] = []
        for job in candidates:
            if _trusted_published_source(job):
                kept.append(job.model_copy(update={"source_readiness": SourceReadiness.READY}))
                continue
            url = str(job.source_url)
            if url in verified_open_urls:
                kept.append(job.model_copy(update={"source_readiness": SourceReadiness.READY}))
                continue
            if _raw_web_only(job):
                # Raw web results remain fail-closed, including URLs which did
                # not receive one of the bounded checks.
                continue
            readiness = (
                SourceReadiness.MANUAL_REQUIRED
                if url in checked_urls
                else SourceReadiness.PROVIDER_LISTED
            )
            kept.append(job.model_copy(update={"source_readiness": readiness}))
        return kept

    def _is_verified_open(self, url: str) -> bool:
        if web_discovery_url_is_error_landing(url):
            return False
        now = datetime.now(timezone.utc)
        with self._cache_lock:
            cached = self._cache.get(url)
        if cached is not None and cached[0] > now:
            return cached[1]

        host = (urlsplit(url).hostname or url).casefold()
        with self._cache_lock:
            host_lock = self._host_locks.setdefault(host, Lock())
        verified_open = False
        with host_lock:
            try:
                document = self.fetcher.fetch(url)
                verified_open = not web_discovery_document_is_error_landing(
                    document.final_url,
                    document.text,
                ) and web_discovery_document_is_individual_job(document.text)
            except UrlIngestionError:
                verified_open = False
        with self._cache_lock:
            self._cache[url] = (now + self.cache_ttl, verified_open)
        return verified_open

    def _is_definitively_closed(self, url: str) -> bool:
        """Compatibility helper: anything not verified open is not publishable."""

        return not self._is_verified_open(url)


class ArbeitnowDiscoveryProvider:
    """Public Europe-oriented feed containing direct ATS and employer jobs."""

    name = "arbeitnow"
    attribution = "Jobs discovered via Arbeitnow"
    attribution_url = "https://www.arbeitnow.com/blog/job-board-api"
    endpoint = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
        max_pages: int = 30,
        cache_seconds: int = 300,
        search_budget_seconds: float = 30.0,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "User-Agent": ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
            },
        )
        self.max_pages = max(1, min(30, max_pages))
        self.cache_seconds = max(0, cache_seconds)
        self.search_budget_seconds = max(1.0, search_budget_seconds)
        self._cached_candidates: list[DiscoveredJob] | None = None
        self._cache_expires_at: datetime | None = None
        self.last_request_count = 0
        self._request_count_lock = Lock()

    def maximum_request_count(self, query: DiscoveryQuery) -> int:
        """Return the largest feed fan-out this search can make."""

        del query
        now = datetime.now(timezone.utc)
        if (
            self._cached_candidates is not None
            and self._cache_expires_at is not None
            and self._cache_expires_at > now
        ):
            return 1
        return self.max_pages

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        candidates = self._candidates()
        primary_tokens = _tokens(" ".join(query.desired_terms)) or _tokens(query.text)
        expanded_tokens = _expanded_tokens(query.text) - primary_tokens
        location_tokens = _tokens(query.location)
        ranked: list[tuple[int, DiscoveredJob]] = []
        unique_candidates = {
            _canonical_url(str(job.source_url)): job for job in candidates
        }.values()
        for job in unique_candidates:
            if not discovered_job_has_structured_role_evidence(query, job):
                continue
            searchable = " ".join(
                (job.title, job.company, job.location, " ".join(job.tags), job.summary)
            ).casefold()
            searchable_tokens = _tokens(searchable)
            primary_hits = len(primary_tokens.intersection(searchable_tokens))
            expanded_hits = len(expanded_tokens.intersection(searchable_tokens))
            phrase_hit = query.text.casefold() in searchable
            if primary_tokens and primary_hits == 0 and expanded_hits == 0 and not phrase_hit:
                continue
            if not _work_arrangement_allows(query, job):
                continue

            # Location is an origin for later commute calculation, not an exact city
            # filter. Nearby roles must remain discoverable.
            location_hits = len(location_tokens.intersection(_tokens(job.location)))
            score = (
                primary_hits * 12
                + expanded_hits * 4
                + (18 if phrase_hit else 0)
                + location_hits * 8
                + (3 if job.remote else 0)
            )
            ranked.append((score, job))
        ranked.sort(
            key=lambda item: (
                -item[0],
                -(item[1].published_at or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp(),
                item[1].title.casefold(),
            )
        )
        return [job for _, job in ranked[: query.limit]]

    def _candidates(self) -> list[DiscoveredJob]:
        now = datetime.now(timezone.utc)
        with self._request_count_lock:
            self.last_request_count = 0
        if (
            self._cached_candidates is not None
            and self._cache_expires_at is not None
            and self._cache_expires_at > now
        ):
            return self._cached_candidates

        candidates: list[DiscoveredJob] = []
        deadline = time.monotonic() + self.search_budget_seconds
        try:
            for page in range(1, self.max_pages + 1):
                if page > 1 and time.monotonic() >= deadline:
                    break
                with self._request_count_lock:
                    self.last_request_count += 1
                response = self.client.get(self.endpoint, params={"page": page})
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", [])
                if not isinstance(rows, list):
                    raise ValueError("job feed did not contain a data list")
                candidates.extend(self._parse(row) for row in rows if isinstance(row, dict))
                if not rows:
                    break
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise DiscoveryError(
                f"Explore could not reach Arbeitnow: {type(exc).__name__}. Try again shortly."
            ) from exc

        self._cached_candidates = candidates
        self._cache_expires_at = now + timedelta(seconds=self.cache_seconds)
        return candidates

    @staticmethod
    def _parse(row: dict[str, object]) -> DiscoveredJob:
        title = str(row.get("title") or "Untitled role").strip()
        company = str(row.get("company_name") or "Employer not stated").strip()
        source_url = str(row.get("url") or "").strip()
        if not source_url:
            raise ValueError("job result did not contain a source URL")
        raw_tags = row.get("tags") or []
        raw_types = row.get("job_types") or []
        tags = [
            str(value).strip()
            for value in [
                *(raw_tags if isinstance(raw_tags, list) else []),
                *(raw_types if isinstance(raw_types, list) else []),
            ]
            if str(value).strip()
        ]
        return DiscoveredJob(
            provider="arbeitnow",
            external_id=str(row.get("slug") or source_url),
            title=title,
            company=company,
            location=str(row.get("location") or "Location not stated").strip(),
            remote=bool(row.get("remote", False)),
            tags=tags[:12],
            summary=_plain_text(str(row.get("description") or ""))[:1_500],
            source_url=source_url,
            published_at=_published_at(row.get("created_at")),
        )


class BraveWebDiscoveryProvider:
    """Optional web-wide discovery through Brave's documented Search API."""

    name = "brave-web"
    attribution = "Web results discovered via Brave Search"
    attribution_url = "https://api.search.brave.com/app/documentation/web-search/get-started"
    endpoint = BRAVE_WEB_SEARCH_ENDPOINT
    blocked_hosts = WEB_DISCOVERY_EXCLUDED_DOMAINS

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Brave Search requires a non-empty API key")
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key.strip(),
            "User-Agent": ("BetterOption/0.7.2k (+https://github.com/ILLVAN/betteroption)"),
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
        search_texts = [*_web_search_texts(query), *_portal_search_texts(query, maximum=5)]
        return max(1, len(search_texts) + (1 if search_texts else 0))

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        self.last_request_count = 0
        regional_locations = _regional_search_locations(query)
        origin = _resolve_discovery_place(query.location, _PLACE_INDEX, _POSTAL_INDEX)
        market_search_lang, ui_lang = _brave_market_language(origin)
        request_headers = (
            _brave_location_headers(origin) if origin is not None and not query.worldwide else None
        )
        jobs: list[DiscoveredJob] = []
        requests: list[tuple[str, int]] = []
        search_texts = [*_web_search_texts(query), *_portal_search_texts(query, maximum=5)]
        requests.extend((focused_search, 0) for focused_search in search_texts)
        request_count = 0
        request_count_lock = Lock()

        def fetch(search_text: str, offset: int) -> tuple[list[DiscoveredJob], bool]:
            nonlocal request_count
            with request_count_lock:
                request_count += 1
            params: dict[str, object] = {
                "q": search_text,
                "count": 20,
                "offset": offset,
                "safesearch": "strict",
                "search_lang": _brave_query_language(search_text, market_search_lang),
                "ui_lang": ui_lang,
                "units": "metric",
                "extra_snippets": True,
                "text_decorations": False,
                "result_filter": "web",
            }
            if origin is not None and not query.worldwide:
                params["country"] = origin.country_code
            page = request_brave_web_page(
                self.client,
                params=params,
                headers=request_headers,
            )
            return (
                [
                    parsed
                    for row in page.results
                    if self._usable(row)
                    if (parsed := self._parse(row, query, regional_locations)) is not None
                ],
                page.more_results_available,
            )

        executor = DaemonThreadPoolExecutor(
            max_workers=min(4, len(requests) or 1),
            thread_name_prefix="brave-discovery",
        )
        futures = [executor.submit(fetch, search_text, offset) for search_text, offset in requests]
        completed, pending = wait(futures, timeout=35)
        successful_requests = 0
        failures: list[BraveSearchError] = []
        first_page_has_more = False
        for future in completed:
            try:
                page_jobs, has_more = future.result()
                jobs.extend(page_jobs)
                if futures and future is futures[0]:
                    first_page_has_more = has_more
                successful_requests += 1
            except BraveSearchError as exc:
                failures.append(exc)
            except (TypeError, ValueError):
                failures.append(
                    BraveSearchResponseError("Brave Web Search returned an unusable result row.")
                )
        non_cancelled_futures = len(completed)
        for future in pending:
            if not future.cancel():
                non_cancelled_futures += 1
        executor.shutdown(wait=False, cancel_futures=True)
        with request_count_lock:
            # Timed-out running calls cannot be cancelled. Count them before
            # returning even when their response misses the Explore deadline.
            self.last_request_count = max(request_count, non_cancelled_futures)

        # Spend the one reserved page-two request only when Brave explicitly
        # says the best focused query has more results. Older code always paid
        # for offset 1, including empty and exhausted result sets.
        if first_page_has_more:
            try:
                page_jobs, _has_more = fetch(search_texts[0], 1)
                jobs.extend(page_jobs)
                successful_requests += 1
            except BraveSearchError as exc:
                failures.append(exc)
            except (TypeError, ValueError):
                failures.append(
                    BraveSearchResponseError("Brave Web Search returned an unusable result row.")
                )
            with request_count_lock:
                self.last_request_count = max(self.last_request_count, request_count)
        if successful_requests == 0:
            if failures:
                raise failures[0]
            if pending:
                raise BraveSearchUnavailableError(
                    "Brave Web Search did not answer within the Explore search budget. "
                    "Retry the dedicated Search probe later."
                )
        return _deduplicate(jobs)[: query.limit]

    def validate_search_access(self) -> None:
        """Make one payload-free Search-plan probe with a fixed public query."""

        request_brave_web_results(
            self.client,
            params={
                "q": "site:example.com",
                "count": 1,
                "safesearch": "strict",
                "text_decorations": False,
                "result_filter": "web",
            },
        )

    def _usable(self, row: object) -> bool:
        if not isinstance(row, dict):
            return False
        value = str(row.get("url") or "").strip()
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not host:
            return False
        if web_discovery_source_is_excluded(value):
            return False
        if web_discovery_url_is_error_landing(value):
            return False
        return web_discovery_result_is_plausible_job(
            value,
            str(row.get("title") or ""),
            _brave_result_summary(row),
        )

    def _parse(
        self,
        row: dict[str, object],
        query: DiscoveryQuery,
        regional_locations: list[str],
    ) -> DiscoveredJob | None:
        url = str(row.get("url") or "").strip()
        if web_discovery_url_is_error_landing(url):
            return None
        profile = row.get("profile")
        company = "Employer source"
        if isinstance(profile, dict):
            company = str(profile.get("long_name") or profile.get("name") or company).strip()
        if company == "Employer source":
            company = (urlsplit(url).hostname or company).removeprefix("www.")
        title = _plain_text(str(row.get("title") or "Job opportunity"))
        summary = _brave_result_summary(row)
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
            provider=self.name,
            external_id=url,
            title=title[:500],
            company=company[:500],
            location=location,
            remote=remote,
            tags=tags,
            summary=summary,
            source_url=url,
        )


def _brave_market_language(origin: ResolvedPlace | None) -> tuple[str, str]:
    """Return one documented Brave search language and interface locale."""

    if origin is None:
        return "en", "en-US"
    return _BRAVE_MARKET_LANGUAGES.get(origin.country_code.upper(), ("en", "en-US"))


def _brave_query_language(search_text: str, fallback: str) -> str:
    """Choose Brave's search language from the generated query, not the city."""

    # Focused discovery queries quote the role before the location. Inspect
    # that first quoted phrase so a city such as ``Neukölln`` does not turn an
    # English role query into a German-language request.
    quoted = re.findall(r'"([^"\n]+)"', search_text)
    folded = (quoted[0] if quoted else search_text).casefold()
    german_signals = (
        "ä",
        "ö",
        "ü",
        "ß",
        "entwickler",
        "hebamme",
        "praktikum",
        "stelle",
        "werkstudent",
        " für ",
    )
    if any(signal in folded for signal in german_signals):
        return "de"
    if re.search(
        r"\b(accountant|administrator|analyst|architect|assurance|backend|consultant|coordinator|customer|data|design|designer|developer|director|engineer|engineering|finance|frontend|intern|lead|manager|marketing|midwife|nurse|operations|product|program|project|python|quality|researcher|sales|scientist|software|specialist|student|support|technician|ux)\b",
        folded,
    ):
        return "en"
    return fallback


def _brave_result_summary(row: dict[str, object]) -> str:
    """Use the extra snippets requested from Brave instead of discarding them."""

    values: list[str] = [str(row.get("description") or "")]
    extra = row.get("extra_snippets")
    if isinstance(extra, list):
        values.extend(str(item) for item in extra if isinstance(item, str))
    return _plain_text(" ".join(values))[:1_500]


def _brave_location_headers(origin: ResolvedPlace) -> dict[str, str]:
    """Build coarse local-search headers from an offline-resolved origin only."""

    city = re.sub(r"^\d{5}\s+", "", origin.label).strip()
    safe_city = " ".join(
        unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode().split()
    )[:100]
    headers = {
        "X-Loc-Lat": f"{origin.latitude:.2f}",
        "X-Loc-Long": f"{origin.longitude:.2f}",
        "X-Loc-Country": origin.country_code.upper(),
    }
    if safe_city:
        headers["X-Loc-City"] = safe_city
    if isinstance(origin, ResolvedPostalCode):
        headers["X-Loc-Postal-Code"] = origin.postal_code
    return headers


class CompositeDiscoveryProvider:
    """Merge independent legal providers without letting one failure erase results."""

    name = "multi-source"

    def __init__(
        self,
        providers: Iterable[JobDiscoveryProvider],
        *,
        place_index: OfflinePlaceIndex | None = None,
    ) -> None:
        self.providers = list(providers)
        if not self.providers:
            raise ValueError("at least one discovery provider is required")
        self.attribution = " + ".join(provider.attribution for provider in self.providers)
        self.attribution_url = self.providers[0].attribution_url
        self.place_index = place_index or _PLACE_INDEX

    @property
    def attributions(self) -> list[DiscoveryAttribution]:
        return [
            DiscoveryAttribution(label=provider.attribution, url=provider.attribution_url)
            for provider in self.providers
        ]

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        result_sets: list[list[DiscoveredJob]] = []
        errors: list[str] = []
        for provider in self.providers:
            try:
                result_sets.append(provider.search(query))
            except (DiscoveryError, BraveSearchError) as exc:
                errors.append(str(exc))
        if not result_sets:
            raise DiscoveryError(" ".join(errors) or "No discovery source was available.")

        # Round-robin keeps one large feed from hiding every result from another.
        combined: list[DiscoveredJob] = []
        index = 0
        while len(combined) < query.limit and any(index < len(items) for items in result_sets):
            for items in result_sets:
                if index < len(items):
                    combined.append(items[index])
            index += 1
        return finalize_discovered_jobs(
            query,
            combined,
            place_index=self.place_index,
        )[: query.limit]


def finalize_discovered_jobs(
    query: DiscoveryQuery,
    jobs: Iterable[DiscoveredJob],
    *,
    place_index: OfflinePlaceIndex | None = None,
) -> list[DiscoveredJob]:
    """Deduplicate, rank, and keep explicit seniority conflicts at the tail."""

    ranked = rank_discovered_jobs(
        query,
        [
            job
            for job in _deduplicate(jobs)
            if discovery_result_is_plausible_individual_job(
                str(job.source_url),
                job.title,
                job.summary,
            )
            and (
                not _raw_web_only(job) or not web_discovery_source_is_excluded(str(job.source_url))
            )
            and _work_arrangement_allows(query, job)
        ],
        place_index=place_index,
    )
    if not query.seniority_targets:
        return ranked
    compatible = [job for job in ranked if not job.seniority_conflict]
    conflicts = [job for job in ranked if job.seniority_conflict]
    # Explicit title-level conflicts do not crowd the primary Compass results.
    # At most two remain visible at the end as transparent stretch discoveries.
    return [*compatible, *conflicts[:2]]


def rank_discovered_jobs(
    query: DiscoveryQuery,
    jobs: Iterable[DiscoveredJob],
    *,
    place_index: OfflinePlaceIndex | None = None,
) -> list[DiscoveredJob]:
    """Rank discoveries by proximity, role evidence, seniority, and exclusions."""

    index = place_index or _PLACE_INDEX
    postal_codes = _POSTAL_INDEX
    origin = _resolve_discovery_place(query.location, index, postal_codes)
    primary_tokens = _tokens(query.text)
    desired_tokens = _tokens(" ".join(query.desired_terms)) or primary_tokens
    expanded_tokens = _expanded_tokens(query.text) - primary_tokens
    structured_role_anchors = structured_role_anchor_tokens(query)
    evaluated_on = datetime.now(timezone.utc).date()
    ranked: list[DiscoveredJob] = []
    for job in jobs:
        searchable = " ".join(
            (job.title, job.company, job.location, " ".join(job.tags), job.summary)
        )
        searchable_tokens = _tokens(searchable)
        title_tokens = _tokens(job.title)
        role_material_tokens = _tokens(" ".join((job.title, job.summary, " ".join(job.tags))))
        role_anchor_hit = bool(structured_role_anchors.intersection(role_material_tokens))
        # A structured Compass search must retain evidence of its leading role
        # concepts.  Proximity alone must not turn a nearby finance or engineering
        # vacancy into a plausible midwife result merely because its description
        # contains a generic word such as ``supporting``.  Free-form Explore
        # searches remain provider-ranked because they do not carry structured
        # role concepts.
        if structured_role_anchors and not role_anchor_hit:
            continue
        desired_ratio = (
            len(desired_tokens.intersection(searchable_tokens)) / len(desired_tokens)
            if desired_tokens
            else 0.0
        )
        title_ratio = (
            len(desired_tokens.intersection(title_tokens)) / len(desired_tokens)
            if desired_tokens
            else 0.0
        )
        expanded_ratio = (
            len(expanded_tokens.intersection(searchable_tokens)) / len(expanded_tokens)
            if expanded_tokens
            else 0.0
        )
        phrase_bonus = 0.15 if query.text.casefold() in searchable.casefold() else 0.0
        keyword_score = min(
            1.0,
            title_ratio * 0.55
            + desired_ratio * 0.3
            + expanded_ratio * 0.15
            + phrase_bonus
            + (0.25 if role_anchor_hit else 0.0),
        )
        observed_seniority = _seniority_bands(job.title, job.tags)
        seniority_score, seniority_conflict, seniority_note = _seniority_fit(
            query.seniority_targets,
            observed_seniority,
        )
        if query.seniority_targets:
            # Missing evidence is not a partial match. Keep the seniority share
            # at zero until the title or structured tags actually support it.
            compass_score = keyword_score * 0.7
            if seniority_score is not None:
                compass_score += seniority_score * 0.3
        else:
            compass_score = keyword_score
        exclusion_signals = _matching_exclusions(query.excluded_terms, searchable)
        if exclusion_signals:
            compass_score *= 0.25

        destination = (
            _resolve_discovery_place(job.location, index, postal_codes)
            if origin and not job.remote
            else None
        )
        distance_km: float | None = None
        distance_score: float | None = None
        if origin and job.remote:
            # Remote is reachable, but it must not automatically outrank every
            # nearby role unless the Compass explicitly prefers remote work.
            distance_score = 1.0 if query.remote_preferred or query.remote_only else 0.42
        elif origin and destination:
            distance_km = straight_line_distance_km(origin, destination)
            # A smooth falloff avoids an arbitrary radius cliff. Roughly 50 km retains
            # half of the proximity component; Matching later uses actual travel time.
            distance_score = math.exp(-distance_km / 72.0)

        if distance_score is not None:
            combined = 0.55 * distance_score + 0.45 * compass_score
        elif origin is not None:
            # Unknown distance cannot receive invented proximity credit. Keyword
            # relevance still orders unresolved places within their own lower band.
            combined = 0.45 * compass_score
        else:
            combined = compass_score
        posting_freshness = classify_posting_date(
            job.published_at.date() if job.published_at is not None else None,
            evaluated_on=evaluated_on,
        )
        combined += posting_date_score_adjustment(posting_freshness) / 100
        if job.remote and query.remote_preferred:
            combined = min(1.0, combined + 0.12)
        if seniority_conflict:
            combined *= 0.35
        combined = max(0.0, min(1.0, combined))
        ranked.append(
            job.model_copy(
                update={
                    "distance_km": distance_km,
                    "distance_relevance": (
                        round(distance_score * 100) if distance_score is not None else None
                    ),
                    "keyword_relevance": round(keyword_score * 100),
                    "seniority_relevance": (
                        round(seniority_score * 100)
                        if query.seniority_targets and seniority_score is not None
                        else None
                    ),
                    "compass_relevance": round(compass_score * 100),
                    "seniority_note": seniority_note,
                    "seniority_conflict": seniority_conflict,
                    "exclusion_signals": exclusion_signals,
                    "search_score": round(combined * 100),
                }
            )
        )
    ranked.sort(
        key=lambda job: (
            _reachability_band(query, job, origin is not None),
            0 if query.remote_preferred and job.remote else 1,
            -(job.search_score or 0),
            job.distance_km if job.distance_km is not None else float("inf"),
            -(job.published_at or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp(),
            job.title.casefold(),
        )
    )
    return ranked


def discovery_query_from_profile(profile: CandidateProfile) -> DiscoveryQuery:
    """Build a broad discovery query from confirmed Compass direction data."""

    preferred_keys = (
        "role.family",
        "role.responsibility",
        "career.direction",
        "industry.sector",
        "skill.desired",
        "skill.name",
    )
    values: list[str] = []
    for key in preferred_keys:
        for fact in profile.confirmed_search_facts:
            if fact.key != key or fact.level == RequirementLevel.EXCLUSION:
                continue
            raw_values = fact.value if isinstance(fact.value, list) else [fact.value]
            for value in raw_values:
                clean = " ".join(str(value).split())
                if clean and clean.casefold() not in {item.casefold() for item in values}:
                    values.append(clean)
            if len(values) >= 12:
                break
        if len(values) >= 12:
            break
    if not values:
        raise DiscoveryError(
            "Confirm at least one desired role, responsibility, industry, or skill in Compass first."
        )

    # Use the same newest-fact projection shown in the Compass widget.  The
    # typed location object is only a legacy fallback inside that projection.
    origin = mobility_widget_preferences(profile).origin_label

    remote_only, onsite_only, remote_preferred = _profile_work_arrangement(profile)
    seniority_targets = _profile_seniority_targets(profile)
    excluded_terms = _profile_excluded_terms(profile)
    return DiscoveryQuery(
        text=" · ".join(_prioritize_search_values(values))[:400],
        location=origin[:200],
        remote_only=remote_only,
        onsite_only=onsite_only,
        remote_preferred=remote_preferred,
        desired_terms=values,
        excluded_terms=excluded_terms,
        seniority_targets=seniority_targets,
        regional_target=30,
    )


def _resolve_discovery_place(
    label: str,
    place_index: OfflinePlaceIndex,
    postal_codes: OfflineGermanPostalCodeIndex,
) -> ResolvedPlace | None:
    """Resolve postcodes before city labels without making a network request."""

    clean = " ".join(label.split())
    if not clean:
        return None
    # Explore may use an explicitly marked representative city when a feed
    # exposes only a NUTS region. Routing never calls this path and continues
    # to require a real city, postcode, or address through ``resolve``.
    return postal_codes.resolve(clean) or place_index.resolve_for_explore(clean)


def _work_arrangement_allows(query: DiscoveryQuery, job: DiscoveredJob) -> bool:
    if query.remote_only:
        return job.remote
    if query.onsite_only:
        return not job.remote
    if not query.include_remote_jobs and job.remote:
        return False
    return True


def _profile_work_arrangement(profile: CandidateProfile) -> tuple[bool, bool, bool]:
    """Translate natural Compass work-model statements into discovery boundaries."""

    remote = False
    onsite = False
    hybrid = False
    remote_must_have = False
    onsite_must_have = False
    relevant_key_markers = ("work_model", "workplace", "work.location", "remote", "onsite")
    for fact in profile.confirmed_search_facts:
        if not any(marker in fact.key.casefold() for marker in relevant_key_markers):
            continue
        material = str(fact.value).casefold().replace("-", " ")
        mentions_hybrid = any(marker in material for marker in ("hybrid", "mixed"))
        mentions_remote = any(
            marker in material
            for marker in ("remote", "homeoffice", "home office", "work from home")
        )
        mentions_onsite = any(
            marker in material
            for marker in ("onsite", "on site", "office based", "vor ort", "präsenz")
        )
        if mentions_hybrid:
            hybrid = True
        if fact.level == RequirementLevel.EXCLUSION:
            remote = remote or mentions_onsite
            onsite = onsite or mentions_remote
        else:
            remote = remote or mentions_remote
            onsite = onsite or mentions_onsite
            if fact.level == RequirementLevel.MUST_HAVE:
                remote_must_have = remote_must_have or mentions_remote
                onsite_must_have = onsite_must_have or mentions_onsite
    if hybrid or (remote and onsite):
        return False, False, remote
    return remote_must_have, onsite_must_have, remote


def provider_attributions(provider: JobDiscoveryProvider) -> list[DiscoveryAttribution]:
    attributions = getattr(provider, "attributions", None)
    if attributions is not None:
        return list(attributions)
    return [DiscoveryAttribution(label=provider.attribution, url=provider.attribution_url)]


def _plain_text(value: str) -> str:
    without_blocks = re.sub(r"</(?:p|li|div|h\d)>", " ", value, flags=re.IGNORECASE)
    without_tags = re.sub(r"<[^>]+>", " ", without_blocks)
    return " ".join(html.unescape(without_tags).split())


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w+#]{2,}", value.casefold(), flags=re.UNICODE))


def _expanded_tokens(value: str) -> set[str]:
    tokens = _tokens(value)
    material = value.casefold()
    expansions = {
        "embedded": {"firmware", "microcontroller", "rtos", "autosar", "c++"},
        "test automation": {
            "testautomatisierung",
            "qa",
            "quality",
            "verification",
            "validation",
            "selenium",
            "pytest",
            "hil",
        },
        "quality assurance": {"qa", "testing", "verification", "validation", "test"},
        "research and development": {"r&d", "research", "development", "prototype"},
        "prototyping": {"prototype", "r&d", "development", "laboratory"},
        "python": {"pytest", "automation", "backend", "scripting"},
        "software": {"developer", "development", "entwickler", "entwicklung"},
        "mechatronics": {"mechatronik", "automation", "robotics"},
    }
    for phrase, additions in expansions.items():
        if phrase in material:
            tokens.update(additions)
    return tokens


# These words describe how almost any job is performed, rather than what the
# occupation is.  They are intentionally ignored only when a phrase contains a
# more specific concept (``supporting childbirth`` therefore anchors on
# ``childbirth``; a genuine one-word search for ``support`` still remains
# usable).
_WEAK_ROLE_ANCHOR_TOKENS = frozenset(
    {
        "arbeit",
        "arbeiten",
        "career",
        "company",
        "job",
        "jobs",
        "opportunity",
        "position",
        "professional",
        "responsibilities",
        "responsibility",
        "responsible",
        "role",
        "roles",
        "support",
        "supporting",
        "team",
        "teams",
        "unterstützen",
        "unterstützung",
        "work",
        "working",
    }
)


def _role_anchor_tokens_for_term(value: str) -> set[str]:
    """Return distinctive occupation evidence for one structured Compass term."""

    raw = _tokens(value)
    distinctive = raw - _WEAK_ROLE_ANCHOR_TOKENS
    anchors = set(distinctive or raw)
    # Existing transparent domain expansions (for example embedded -> firmware
    # and test automation -> QA) are useful role evidence too, but generic
    # expansions cannot make an unrelated result pass the gate.
    anchors.update(_expanded_tokens(value) - raw - _WEAK_ROLE_ANCHOR_TOKENS)
    for equivalent in _german_english_role_variants(value):
        anchors.update(_tokens(equivalent))
    return anchors


def structured_role_anchor_tokens(query: DiscoveryQuery) -> set[str]:
    """Build the query-scoped role anchors used by feeds and final ranking.

    ``desired_terms`` are ordered by ``discovery_query_from_profile`` with role
    family/responsibility before secondary skills.  Limiting the hard gate to
    the first three concepts prevents an incidental generic skill from admitting
    an otherwise unrelated nearby vacancy, while still allowing synonyms and a
    small family of role descriptions.
    """

    if not query.desired_terms:
        return set()
    anchors: set[str] = set()
    for term in query.desired_terms[:3]:
        anchors.update(_role_anchor_tokens_for_term(term))
    return anchors


def discovered_job_has_structured_role_evidence(
    query: DiscoveryQuery,
    job: DiscoveredJob,
) -> bool:
    """Return whether a job supports a structured query's leading role concepts."""

    anchors = structured_role_anchor_tokens(query)
    if not anchors:
        return True
    material = _tokens(" ".join((job.title, job.summary, " ".join(job.tags))))
    return bool(anchors.intersection(material))


def _prioritize_search_values(values: list[str]) -> list[str]:
    """Keep precise role concepts ahead of generic ontology fragments."""

    generic = {
        "engineering",
        "development",
        "software",
        "technology",
        "junior",
        "professional",
    }
    specific = [value for value in values if value.casefold() not in generic]
    broad = [value for value in values if value.casefold() in generic]
    return [*specific[:8], *broad[:2]]


_GERMAN_ENGLISH_ROLE_EQUIVALENTS: tuple[tuple[str, str], ...] = (
    ("midwife", "hebamme"),
    ("registered nurse", "pflegefachkraft"),
    ("nurse", "pflegefachkraft"),
    ("physiotherapist", "physiotherapeut"),
    ("occupational therapist", "ergotherapeut"),
    ("doctor", "arzt"),
    ("teacher", "lehrer"),
    ("social worker", "sozialarbeiter"),
    ("accountant", "buchhalter"),
    ("electrician", "elektriker"),
    ("mechanical engineer", "maschinenbauingenieur"),
    ("software developer", "softwareentwickler"),
    ("project manager", "projektmanager"),
    ("sales manager", "vertriebsleiter"),
    ("warehouse worker", "lagermitarbeiter"),
    ("customer service", "kundenservice"),
)


def _targets_german_market(query: DiscoveryQuery) -> bool:
    """Return whether bounded bilingual role expansion is useful for this search."""

    origin = _resolve_discovery_place(query.location, _PLACE_INDEX, _POSTAL_INDEX)
    if origin is not None:
        return origin.country_code == "DE"
    folded = " ".join(query.location.casefold().split())
    return folded in {"de", "deutschland", "germany"}


def _german_english_role_variants(term: str) -> list[str]:
    """Return exact occupation equivalents, without translating arbitrary prose.

    The small occupation lexicon is deliberately generic and symmetric.  It
    improves recall for German-market searches without sending user text to a
    translation provider or weakening exclusions through free-form rewriting.
    """

    normalized = " ".join(term.casefold().split())
    variants: list[str] = []
    for english, german in _GERMAN_ENGLISH_ROLE_EQUIVALENTS:
        if normalized == english:
            variants.append(german)
        elif normalized == german:
            variants.append(english)
    return variants


def _web_search_texts(query: DiscoveryQuery) -> list[str]:
    """Create bounded role-by-locality searches instead of one oversized query."""

    terms = _prioritize_search_values(query.desired_terms)
    if not terms:
        # Stored/custom searches do not always have structured desired_terms.
        # Split their human sentence into small independent requests instead of
        # sending one keyword-heavy query that broad providers may under-return.
        terms = [
            clean
            for part in re.split(r"\s*[·|;,]\s*|\s+\bor\b\s+", query.text, flags=re.I)
            if (clean := " ".join(part.split()))
        ] or [query.text.replace("·", " ")]
    role_terms = list(terms[:4])
    if _targets_german_market(query):
        for term in terms[:4]:
            for variant in _german_english_role_variants(term):
                if variant.casefold() not in {item.casefold() for item in role_terms}:
                    role_terms.append(variant)
    role_phrases = [f'"{term}"' for term in role_terms[:8]]
    seniority = " ".join(_seniority_search_terms(query.seniority_targets))
    exclusions = " ".join(
        f"-{term.casefold()}"
        for term in query.excluded_terms[:6]
        if re.fullmatch(r"[\wÀ-ɏ-]{2,30}", term.strip(), flags=re.UNICODE)
    )
    locations = _regional_search_locations(query) or [query.location.strip() or "jobs"]
    focused: list[str] = []
    # Cover every role concept at the strongest locality before widening the
    # radius. This keeps German and English occupation equivalents inside the
    # first Exa batch while retaining independent, concise requests.
    pairs = [(location, role) for location in locations[:5] for role in role_phrases]
    for location, role in pairs:
        value = " ".join(
            part
            for part in (
                role,
                seniority,
                f'"{location}"',
                "job",
                exclusions,
            )
            if part
        )
        if value.casefold() not in {item.casefold() for item in focused}:
            focused.append(value)
        if len(focused) >= 16:
            return focused
    return focused[:16]


def _portal_search_texts(
    query: DiscoveryQuery,
    *,
    maximum: int = MAX_PORTAL_SEARCH_SCOPES,
) -> list[str]:
    """Create bounded site hints for already validated persona portals."""

    values: list[str] = []
    if not query.include_custom_portals:
        return values
    for host, path in _portal_scopes(query)[: max(0, maximum)]:
        scope = f"{host}{path}"
        if host and re.fullmatch(r"[a-z0-9.-]+", host):
            values.append(
                " ".join(
                    part
                    for part in (
                        f"site:{scope}",
                        query.text.replace("·", " ").strip(),
                        query.location.strip(),
                        "job",
                    )
                    if part
                )
            )
    return values


def _regional_search_locations(
    query: DiscoveryQuery,
    *,
    place_index: OfflinePlaceIndex | None = None,
    postal_codes: OfflineGermanPostalCodeIndex | None = None,
) -> list[str]:
    """Resolve an origin and nearby city anchors entirely from bundled data."""

    if not query.location.strip():
        return []
    index = place_index or _PLACE_INDEX
    postcode_index = postal_codes or _POSTAL_INDEX
    origin = _resolve_discovery_place(query.location, index, postcode_index)
    if origin is None:
        return [query.location.strip()]
    anchor = re.sub(r"^\d{5}\s+", "", origin.label).strip()
    search_origin = origin.model_copy(update={"label": anchor})
    places = [search_origin, *index.nearby(anchor, maximum_distance_km=120, limit=10)]
    labels: list[str] = []
    for place in places:
        label = place.label.strip()
        if label and label.casefold() not in {item.casefold() for item in labels}:
            labels.append(label)
    return labels[:10]


def _location_from_search_material(
    material: str,
    query: DiscoveryQuery,
    regional_locations: list[str],
) -> str:
    """Use only an explicitly visible postcode or place name as web-result location."""

    postcode = _POSTAL_INDEX.resolve(material)
    if postcode is not None:
        return postcode.label
    material_tokens = _tokens(material)
    for location in regional_locations:
        location_tokens = _place_identity_tokens(location)
        if location_tokens and location_tokens.issubset(material_tokens):
            return location
    # Also recover the exact requested locality when it is visible but the
    # offline index could not resolve a district or smaller town.
    requested_tokens = _place_identity_tokens(query.location)
    if requested_tokens and requested_tokens.issubset(material_tokens):
        return query.location.strip()
    return "Location to verify"


def _market_safe_web_location(
    title: str,
    summary: str,
    query: DiscoveryQuery,
    regional_locations: list[str],
    *,
    remote: bool,
    source_url: str = "",
) -> str | None:
    """Reject web snippets that cannot prove they belong to the requested market.

    Semantic search excerpts can echo the query location even when the linked
    vacancy is on another continent. Explicit title and source-market evidence
    therefore takes precedence over a locality mentioned only in the excerpt.
    Results with no contradictory place evidence remain visibly unresolved
    instead of receiving invented proximity. Direct feeds and ATS connectors
    retain their own structured location handling.
    """

    if not query.location.strip():
        return _location_from_search_material(
            f"{title} {summary}",
            query,
            regional_locations,
        )
    title_location = _location_from_search_material(title, query, regional_locations)
    if title_location != "Location to verify":
        return title_location
    origin = _resolve_discovery_place(
        query.location,
        _PLACE_INDEX,
        _POSTAL_INDEX,
    )
    title_place = _PLACE_INDEX.resolve(
        title,
        preferred_country_code=origin.country_code if origin is not None else "",
    )
    if origin is not None and title_place is not None:
        if not query.worldwide and not _same_discovery_market(
            origin.country_code,
            title_place.country_code,
        ):
            return None
        return title_place.label
    source_market = _source_market_code(source_url)
    if (
        origin is not None
        and source_market is not None
        and not query.worldwide
        and not _same_discovery_market(origin.country_code, source_market)
    ):
        return None
    if remote and origin is not None:
        visible_tokens = _tokens(f"{title} {summary}")
        market_terms = _market_terms(origin.country_code)
        if any(_tokens(term).issubset(visible_tokens) for term in market_terms):
            return f"Remote · {origin.country_code}"
        if query.worldwide:
            return "Remote"
        return None
    material_location = _location_from_search_material(
        f"{title} {summary}",
        query,
        regional_locations,
    )
    return material_location


def _same_discovery_market(origin_code: str, candidate_code: str) -> bool:
    """Stay on the origin continent without imposing a Europe-only default."""

    if origin_code == candidate_code:
        return True
    origin_continent = country_continent_code(origin_code)
    candidate_continent = country_continent_code(candidate_code)
    return bool(origin_continent and origin_continent == candidate_continent)


def _market_terms(country_code: str) -> set[str]:
    """Return transparent country and continent markers for remote snippets."""

    terms = set(country_search_terms(country_code))
    continent = country_continent_code(country_code)
    continent_terms = {
        "AF": {"africa", "african"},
        "AS": {"asia", "asian"},
        "EU": {"europe", "european", "european union", "eu"},
        "NA": {"north america", "north american"},
        "OC": {"oceania"},
        "SA": {"south america", "south american"},
    }
    terms.update(continent_terms.get(continent or "", set()))
    return terms


def _source_market_code(source_url: str) -> str | None:
    """Read an explicit country subdomain or ccTLD without guessing a location."""

    host = (urlsplit(source_url).hostname or "").casefold()
    if not host:
        return None
    labels = [label for label in host.split(".") if label]
    genericized_country_domains = {"ai", "co", "io", "me", "tv"}
    if labels and len(labels[-1]) == 2 and labels[-1] not in genericized_country_domains:
        return labels[-1].upper()
    if len(labels) >= 3 and len(labels[0]) == 2:
        return labels[0].upper()
    return None


def _place_identity_tokens(value: str) -> set[str]:
    stopwords = {
        "am",
        "an",
        "at",
        "bei",
        "der",
        "deutschland",
        "germany",
        "im",
        "in",
        "the",
        "vor",
    }
    meaningful = [
        token for token in _tokens(value) if token not in stopwords and not token.isdigit()
    ]
    if not meaningful:
        return set()
    # The first two meaningful components preserve identities such as Bad Homburg,
    # while Frankfurt am Main still matches a visible "Frankfurt" label.
    return set(meaningful[:2] if len(meaningful[0]) <= 4 else meaningful[:1])


def _remote_only_signal(material: str) -> bool:
    """Avoid treating every mention of hybrid flexibility as remote-only work."""

    normalized = " ".join(material.casefold().replace("-", " ").split())
    return bool(
        re.search(
            r"(?:^|\b)(?:fully remote|remote only|remote job|100\s*%\s*remote|"
            r"work from anywhere|location\s*[:\-]\s*remote|remote\s*\|)\b",
            normalized,
        )
    )


def _reachability_band(
    query: DiscoveryQuery,
    job: DiscoveredJob,
    has_origin: bool,
) -> int:
    """Keep roughly two-hour local opportunities ahead of remote and far-away roles."""

    if not has_origin:
        return 0
    if job.remote:
        return 0 if query.remote_preferred or query.remote_only else 2
    if job.distance_km is None:
        return 4
    if job.distance_km <= 80:
        return 0
    if job.distance_km <= 150:
        return 1
    return 3


SENIORITY_MARKERS: dict[SeniorityBand, tuple[str, ...]] = {
    SeniorityBand.INTERN: (
        "intern",
        "internship",
        "working student",
        "werkstudent",
        "praktikum",
        "trainee",
    ),
    SeniorityBand.JUNIOR: (
        "junior",
        "entry level",
        "entry-level",
        "graduate",
        "berufseinsteiger",
        "young professional",
    ),
    SeniorityBand.MID: ("mid level", "mid-level", "professional"),
    SeniorityBand.SENIOR: ("senior", "sr.", "sr ", "experienced professional"),
    SeniorityBand.LEAD: ("lead", "principal", "staff engineer", "architect", "head of"),
    SeniorityBand.MANAGER: ("manager", "director", "teamleiter", "leiter", "vp "),
}


def _profile_seniority_targets(profile: CandidateProfile) -> list[SeniorityBand]:
    targets: list[SeniorityBand] = []
    for fact in profile.confirmed_search_facts:
        if fact.level == RequirementLevel.EXCLUSION or not any(
            marker in fact.key
            for marker in ("seniority", "career.level", "experience.level", "role.level")
        ):
            continue
        for band in _seniority_bands(str(fact.value), []):
            if band not in targets:
                targets.append(band)
    return targets


def _profile_excluded_terms(profile: CandidateProfile) -> list[str]:
    terms: list[str] = []
    for fact in profile.confirmed_search_facts:
        if fact.level != RequirementLevel.EXCLUSION:
            continue
        values = fact.value if isinstance(fact.value, list) else [fact.value]
        for value in values:
            clean = " ".join(str(value).split())
            if (
                clean
                and len(clean) <= 100
                and clean.casefold() not in {item.casefold() for item in terms}
            ):
                terms.append(clean)
    return terms[:30]


def _seniority_bands(text: str, tags: list[str]) -> list[SeniorityBand]:
    material = f"{text} {' '.join(tags)}".casefold()
    bands: list[SeniorityBand] = []
    for band, markers in SENIORITY_MARKERS.items():
        if any(_contains_search_marker(material, marker) for marker in markers):
            bands.append(band)
    return bands


def _contains_search_marker(material: str, marker: str) -> bool:
    """Match a title/search phrase without treating ``international`` as ``intern``."""

    clean_marker = marker.casefold().strip()
    if not clean_marker:
        return False
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(clean_marker)}(?![a-z0-9])",
            material.casefold(),
        )
    )


def _seniority_fit(
    targets: list[SeniorityBand],
    observed: list[SeniorityBand],
) -> tuple[float | None, bool, str | None]:
    if not targets:
        return 1.0, False, None
    target_set = set(targets)
    observed_set = set(observed)
    if not observed_set:
        return None, False, "The title does not state a seniority level."
    if target_set.intersection(observed_set):
        labels = ", ".join(sorted(band.value for band in observed_set))
        return 1.0, False, f"The title signals {labels}, aligned with the Compass target."
    junior_target = bool(target_set.intersection({SeniorityBand.INTERN, SeniorityBand.JUNIOR}))
    senior_job = bool(
        observed_set.intersection({SeniorityBand.SENIOR, SeniorityBand.LEAD, SeniorityBand.MANAGER})
    )
    senior_target = bool(
        target_set.intersection({SeniorityBand.SENIOR, SeniorityBand.LEAD, SeniorityBand.MANAGER})
    )
    junior_job = bool(observed_set.intersection({SeniorityBand.INTERN, SeniorityBand.JUNIOR}))
    if (junior_target and senior_job) or (senior_target and junior_job):
        wanted = ", ".join(sorted(band.value for band in target_set))
        found = ", ".join(sorted(band.value for band in observed_set))
        return 0.0, True, f"Compass targets {wanted}; the title explicitly signals {found}."
    return (
        0.55,
        False,
        "The stated level is adjacent to, but not identical with, the Compass target.",
    )


def _matching_exclusions(exclusions: list[str], searchable: str) -> list[str]:
    material = searchable.casefold()
    signals: list[str] = []
    for exclusion in exclusions:
        meaningful = {
            token
            for token in _tokens(exclusion)
            if token not in {"no", "not", "none", "without", "kein", "keine", "nicht"}
        }
        if meaningful and len(meaningful.intersection(_tokens(material))) / len(meaningful) >= 0.6:
            signals.append(exclusion)
    return signals[:5]


def _seniority_search_terms(targets: list[SeniorityBand]) -> list[str]:
    terms: list[str] = []
    if SeniorityBand.INTERN in targets:
        terms.extend(("intern", "working student"))
    if SeniorityBand.JUNIOR in targets:
        terms.extend(("junior", "entry level"))
    if SeniorityBand.MID in targets:
        terms.append("professional")
    if SeniorityBand.SENIOR in targets:
        terms.append("senior")
    if SeniorityBand.LEAD in targets:
        terms.extend(("lead", "principal"))
    if SeniorityBand.MANAGER in targets:
        terms.append("manager")
    return terms


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/") or "/"
    identity_query = sorted(
        (key.casefold(), item)
        for key, item in _safe_query_pairs(parsed.query)
        if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_QUERY_KEYS
    )
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            urlencode(identity_query),
            "",
        )
    )


def _deduplicate(jobs: Iterable[DiscoveredJob]) -> list[DiscoveredJob]:
    unique: dict[str, DiscoveredJob] = {}
    for job in jobs:
        identity = _canonical_url(str(job.source_url))
        existing = unique.get(identity)
        if existing is None:
            unique[identity] = job.model_copy(
                update={"source_providers": list(job.effective_source_providers)}
            )
            continue
        providers = list(
            dict.fromkeys([*existing.effective_source_providers, *job.effective_source_providers])
        )
        winner = (
            job
            if _discovery_evidence_quality(job) > _discovery_evidence_quality(existing)
            else existing
        )
        other = existing if winner is job else job
        readiness = (
            SourceReadiness.READY
            if SourceReadiness.READY in {existing.source_readiness, job.source_readiness}
            else (
                SourceReadiness.MANUAL_REQUIRED
                if SourceReadiness.MANUAL_REQUIRED
                in {existing.source_readiness, job.source_readiness}
                else SourceReadiness.PROVIDER_LISTED
            )
        )
        updates: dict[str, object] = {
            "source_providers": providers,
            "source_readiness": readiness,
        }
        if (
            winner.published_at is None
            and other.published_at is not None
            and _same_discovery_subject(winner, other)
        ):
            updates["published_at"] = other.published_at
        unique[identity] = winner.model_copy(update=updates)
    return list(unique.values())


def _discovery_evidence_quality(job: DiscoveredJob) -> tuple[int, int, int, int]:
    """Choose the richer duplicate independently of provider identity."""

    location_known = job.location.casefold() not in {
        "",
        "location not stated",
        "location to verify",
    }
    company_specific = (
        job.company.casefold()
        not in {
            "",
            "employer",
            "employer source",
        }
        and "." not in job.company
    )
    summary_length = min(1_500, len(job.summary.strip()))
    return (
        int(location_known) + int(company_specific) + int(summary_length > 0),
        summary_length,
        int(location_known),
        int(company_specific),
    )


def _same_discovery_subject(first: DiscoveredJob, second: DiscoveredJob) -> bool:
    """Require matching human-facing identity before borrowing date evidence."""

    def normalized(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    return normalized(first.title) == normalized(second.title) and normalized(
        first.company
    ) == normalized(second.company)


def _published_at(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
