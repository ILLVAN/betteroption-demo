"""Secret-safe, explicitly invoked OpenWebNinja JSearch access diagnostic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import httpx

from .discovery import DiscoveryQuery
from .providers.openwebninja_jsearch import (
    DEFAULT_JSEARCH_POOL_TIMEOUT_SECONDS,
    DEFAULT_JSEARCH_WRITE_TIMEOUT_SECONDS,
    JSearchAuthenticationError,
    JSearchConnectTimeoutError,
    JSearchConnectionError,
    JSearchDnsError,
    JSearchPlanError,
    JSearchPoolTimeoutError,
    JSearchProviderUnavailableError,
    JSearchProxyError,
    JSearchRateLimitError,
    JSearchReadTimeoutError,
    JSearchRequestError,
    JSearchResponseError,
    JSearchTimeoutError,
    JSearchTlsError,
    JSearchUnavailableError,
    JSearchWriteTimeoutError,
    OpenWebNinjaJSearchProvider,
)
from .settings import Settings


class JSearchDiagnosticCategory(StrEnum):
    """Sanitized outcomes which are safe to print or copy into a bug report."""

    SUCCESS = "success"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION = "authentication"
    PLAN = "plan"
    RATE_LIMIT = "rate_limit"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    WRITE_TIMEOUT = "write_timeout"
    POOL_TIMEOUT = "pool_timeout"
    # Retained for compatibility and for a provider-wide deadline expiry which
    # did not originate in one particular HTTP phase.
    TIMEOUT = "timeout"
    DNS = "dns"
    TLS = "tls"
    PROXY = "proxy"
    CONNECTION = "connection"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    # Retained only for compatibility with diagnostic records produced before
    # v0.7.2b. New probes emit a specific transport or provider category.
    NETWORK = "network"
    REQUEST = "request"
    RESPONSE = "response"
    PROVIDER = "provider"


@dataclass(frozen=True)
class JSearchDiagnostic:
    """The complete diagnostic result; deliberately no request or response data."""

    category: JSearchDiagnosticCategory
    result_count: int

    @property
    def success(self) -> bool:
        return self.category is JSearchDiagnosticCategory.SUCCESS

    @property
    def detail(self) -> str:
        """Fixed, secret-safe explanation for terminal diagnostics."""

        return _DIAGNOSTIC_DETAILS[self.category]

    @property
    def next_step(self) -> str:
        """Fixed, actionable guidance which contains no request metadata."""

        return _DIAGNOSTIC_NEXT_STEPS[self.category]


_DIAGNOSTIC_DETAILS = {
    JSearchDiagnosticCategory.SUCCESS: (
        "The key, endpoint access, and current response schema are working."
    ),
    JSearchDiagnosticCategory.NOT_CONFIGURED: ("No OpenWebNinja JSearch API key is configured."),
    JSearchDiagnosticCategory.AUTHENTICATION: ("OpenWebNinja rejected the configured API key."),
    JSearchDiagnosticCategory.PLAN: (
        "The configured account cannot use the direct JSearch endpoint."
    ),
    JSearchDiagnosticCategory.RATE_LIMIT: (
        "The current JSearch request or plan allowance is exhausted."
    ),
    JSearchDiagnosticCategory.CONNECT_TIMEOUT: (
        "The JSearch connection phase exceeded its bounded timeout."
    ),
    JSearchDiagnosticCategory.READ_TIMEOUT: (
        "JSearch connected but did not return response data within the bounded read window."
    ),
    JSearchDiagnosticCategory.WRITE_TIMEOUT: (
        "The small JSearch GET request could not be written within its bounded timeout."
    ),
    JSearchDiagnosticCategory.POOL_TIMEOUT: (
        "The local JSearch HTTP client could not acquire a connection in time."
    ),
    JSearchDiagnosticCategory.TIMEOUT: (
        "The JSearch provider exceeded its bounded whole-search deadline."
    ),
    JSearchDiagnosticCategory.DNS: ("The JSearch API hostname could not be resolved."),
    JSearchDiagnosticCategory.TLS: (
        "Python could not establish or verify the JSearch TLS connection."
    ),
    JSearchDiagnosticCategory.PROXY: ("The configured HTTPS proxy could not connect to JSearch."),
    JSearchDiagnosticCategory.CONNECTION: (
        "The JSearch host connection failed after DNS and before an HTTP response."
    ),
    JSearchDiagnosticCategory.PROVIDER_UNAVAILABLE: (
        "JSearch returned a provider-side HTTP 5xx response."
    ),
    JSearchDiagnosticCategory.NETWORK: (
        "A legacy diagnostic recorded an unspecified endpoint availability failure."
    ),
    JSearchDiagnosticCategory.REQUEST: ("JSearch rejected the fixed diagnostic request."),
    JSearchDiagnosticCategory.RESPONSE: (
        "JSearch returned JSON that did not match a supported success envelope."
    ),
    # Kept for compatibility with diagnostic records produced before the
    # request/response split. New probes no longer emit this broad category.
    JSearchDiagnosticCategory.PROVIDER: ("JSearch returned an unclassified provider failure."),
}

_DIAGNOSTIC_NEXT_STEPS = {
    JSearchDiagnosticCategory.SUCCESS: (
        "Run Explore again; zero jobs can still be a legitimate search result."
    ),
    JSearchDiagnosticCategory.NOT_CONFIGURED: (
        "Set OPENWEBNINJA_JSEARCH_API_KEY in the local .env file, restart, and rerun."
    ),
    JSearchDiagnosticCategory.AUTHENTICATION: (
        "Replace the local key with an active OpenWebNinja API key and rerun."
    ),
    JSearchDiagnosticCategory.PLAN: (
        "Confirm JSearch access for this key in the OpenWebNinja account dashboard."
    ),
    JSearchDiagnosticCategory.RATE_LIMIT: (
        "Wait for the provider allowance to reset or review the account plan before rerunning."
    ),
    JSearchDiagnosticCategory.CONNECT_TIMEOUT: (
        "Check HTTPS_PROXY, ALL_PROXY, NO_PROXY, DNS, and TCP port 443 for api.openwebninja.com."
    ),
    JSearchDiagnosticCategory.READ_TIMEOUT: (
        "The endpoint was reached; retry later once and report a repeated read_timeout to OpenWebNinja."
    ),
    JSearchDiagnosticCategory.WRITE_TIMEOUT: (
        "Check the local proxy or security software, then rerun the one-request probe."
    ),
    JSearchDiagnosticCategory.POOL_TIMEOUT: (
        "Restart the process and report pool_timeout if the standalone probe repeats it."
    ),
    JSearchDiagnosticCategory.TIMEOUT: (
        "Reduce focused variants or raise the provider budget before rerunning."
    ),
    JSearchDiagnosticCategory.DNS: (
        "Resolve api.openwebninja.com in PowerShell and review local DNS filtering if it fails."
    ),
    JSearchDiagnosticCategory.TLS: (
        "Check the system clock and any HTTPS inspection; configure SSL_CERT_FILE when a local CA is required."
    ),
    JSearchDiagnosticCategory.PROXY: (
        "Check HTTPS_PROXY, ALL_PROXY and NO_PROXY, then rerun the one-request probe."
    ),
    JSearchDiagnosticCategory.CONNECTION: (
        "Check whether a firewall blocks api.openwebninja.com on port 443, then rerun."
    ),
    JSearchDiagnosticCategory.PROVIDER_UNAVAILABLE: (
        "The local connection worked; retry later or check OpenWebNinja provider status."
    ),
    JSearchDiagnosticCategory.NETWORK: (
        "Rerun with v0.7.2b or later to obtain a specific transport category."
    ),
    JSearchDiagnosticCategory.REQUEST: (
        "Verify endpoint access in the provider dashboard; if it persists, update the adapter."
    ),
    JSearchDiagnosticCategory.RESPONSE: (
        "Retest with the latest BetterOption release; if it persists, report this category."
    ),
    JSearchDiagnosticCategory.PROVIDER: (
        "Retest with the latest BetterOption release and report this category if it persists."
    ),
}


def check_jsearch_access(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
    connect_timeout_seconds: float | None = None,
    read_timeout_seconds: float | None = None,
    write_timeout_seconds: float = DEFAULT_JSEARCH_WRITE_TIMEOUT_SECONDS,
    pool_timeout_seconds: float = DEFAULT_JSEARCH_POOL_TIMEOUT_SECONDS,
    search_budget_seconds: float | None = None,
) -> JSearchDiagnostic:
    """Make at most one synthetic JSearch request and return a sanitized result.

    The probe never uses a Compass, profile, job, or user-supplied search term. It
    disables the adapter's normal retry and query fan-out, does not use the
    operations ledger, and intentionally discards the response after counting
    parseable public job rows.
    """

    api_key = settings.openwebninja_jsearch_api_key_value
    if not api_key:
        return JSearchDiagnostic(JSearchDiagnosticCategory.NOT_CONFIGURED, 0)

    provider = OpenWebNinjaJSearchProvider(
        api_key,
        client=client,
        connect_timeout_seconds=(
            settings.openwebninja_jsearch_connect_timeout_seconds
            if connect_timeout_seconds is None
            else connect_timeout_seconds
        ),
        read_timeout_seconds=(
            settings.openwebninja_jsearch_read_timeout_seconds
            if read_timeout_seconds is None
            else read_timeout_seconds
        ),
        write_timeout_seconds=write_timeout_seconds,
        pool_timeout_seconds=pool_timeout_seconds,
        search_budget_seconds=(
            settings.openwebninja_jsearch_search_budget_seconds
            if search_budget_seconds is None
            else search_budget_seconds
        ),
        max_requests=1,
        max_transient_retries=0,
    )
    try:
        jobs = provider.search(
            DiscoveryQuery(
                text="software developer",
                # Use the provider's documented non-US request shape rather
                # than an unlocated query which silently defaults to the US.
                location="Berlin",
                limit=10,
                include_custom_portals=False,
            )
        )
    except JSearchAuthenticationError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.AUTHENTICATION, 0)
    except JSearchPlanError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.PLAN, 0)
    except JSearchRateLimitError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.RATE_LIMIT, 0)
    except JSearchConnectTimeoutError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.CONNECT_TIMEOUT, 0)
    except JSearchReadTimeoutError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.READ_TIMEOUT, 0)
    except JSearchWriteTimeoutError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.WRITE_TIMEOUT, 0)
    except JSearchPoolTimeoutError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.POOL_TIMEOUT, 0)
    except JSearchTimeoutError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.TIMEOUT, 0)
    except JSearchDnsError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.DNS, 0)
    except JSearchTlsError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.TLS, 0)
    except JSearchProxyError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.PROXY, 0)
    except JSearchConnectionError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.CONNECTION, 0)
    except JSearchProviderUnavailableError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.PROVIDER_UNAVAILABLE, 0)
    except JSearchUnavailableError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.NETWORK, 0)
    except JSearchRequestError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.REQUEST, 0)
    except JSearchResponseError:
        return JSearchDiagnostic(JSearchDiagnosticCategory.RESPONSE, 0)
    finally:
        provider.close()

    return JSearchDiagnostic(JSearchDiagnosticCategory.SUCCESS, len(jobs))
