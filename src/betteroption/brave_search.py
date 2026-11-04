"""Shared, secret-safe handling for Brave's Search product.

BetterOption uses Brave Web Search results as discovery candidates.  It does
not call Brave Answers, so an Answers-only subscription token cannot replace a
Search-plan token here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx


BRAVE_WEB_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchError(RuntimeError):
    """Base class for safe Brave Search failures recorded in provider telemetry."""


class BraveSearchAuthenticationError(BraveSearchError):
    """The Search endpoint rejected the supplied subscription token."""


class BraveSearchPlanError(BraveSearchError):
    """The token is not authorized for the Search product or billing is inactive."""


class BraveSearchRateLimitError(BraveSearchError):
    """The Search plan's request or credit allowance is currently exhausted."""


class BraveSearchRequestError(BraveSearchError):
    """The Search endpoint rejected BetterOption's request shape."""


class BraveSearchUnavailableError(BraveSearchError):
    """The Search service could not be reached or returned a server failure."""


class BraveSearchResponseError(BraveSearchError):
    """The Search endpoint returned an unexpected, non-secret response shape."""


@dataclass(frozen=True)
class BraveWebSearchPage:
    """One bounded Web Search page plus Brave's pagination signal."""

    results: list[dict[str, object]]
    more_results_available: bool = False


def _raise_for_status(response: httpx.Response) -> None:
    """Translate HTTP status only; never retain a response body or request URL."""

    status = response.status_code
    if status < 400:
        return
    if status == 401:
        raise BraveSearchAuthenticationError(
            "Brave Web Search rejected BRAVE_SEARCH_API_KEY (HTTP 401). Create or copy "
            "a key from an active Brave Search plan; an Answers-plan key is not a "
            "substitute."
        )
    if status in {402, 403}:
        raise BraveSearchPlanError(
            f"Brave Web Search denied Search-product access (HTTP {status}). Verify that "
            "the key belongs to an active Search plan with billing or credits available; "
            "BetterOption does not call the separate Answers product."
        )
    if status == 429:
        raise BraveSearchRateLimitError(
            "Brave Web Search reached its Search-plan rate or credit limit (HTTP 429). "
            "Check Search usage and billing in the Brave API dashboard, then retry."
        )
    if 400 <= status < 500:
        raise BraveSearchRequestError(
            f"Brave Web Search rejected the request (HTTP {status}). Run the dedicated "
            "Search probe and check the current Web Search API configuration."
        )
    raise BraveSearchUnavailableError(
        f"Brave Web Search is temporarily unavailable (HTTP {status}). Retry later."
    )


def request_brave_web_page(
    client: httpx.Client,
    *,
    params: Mapping[str, object],
    headers: Mapping[str, str] | None = None,
) -> BraveWebSearchPage:
    """Return one Web Search page with secret-safe failure classification."""

    try:
        response = client.get(
            BRAVE_WEB_SEARCH_ENDPOINT,
            params=dict(params),
            headers=dict(headers) if headers else None,
        )
    except httpx.HTTPError as exc:
        raise BraveSearchUnavailableError(
            "Brave Web Search could not be reached. Check the network and retry the "
            "dedicated Search probe."
        ) from exc
    _raise_for_status(response)
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise BraveSearchResponseError(
            "Brave Web Search returned a response that was not valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise BraveSearchResponseError(
            "Brave Web Search returned an unexpected top-level response."
        )
    web = payload.get("web")
    if web is None:
        return BraveWebSearchPage(results=[])
    if not isinstance(web, dict):
        raise BraveSearchResponseError(
            "Brave Web Search returned an unexpected web-result container."
        )
    rows = web.get("results", [])
    if not isinstance(rows, list):
        raise BraveSearchResponseError("Brave Web Search returned an unexpected web-result list.")
    query = payload.get("query")
    more_results_available = bool(
        isinstance(query, dict) and query.get("more_results_available") is True
    )
    return BraveWebSearchPage(
        results=[row for row in rows if isinstance(row, dict)],
        more_results_available=more_results_available,
    )


def request_brave_web_results(
    client: httpx.Client,
    *,
    params: Mapping[str, object],
    headers: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Compatibility wrapper for consumers which need only result rows."""

    return request_brave_web_page(client, params=params, headers=headers).results


_FAILURE_GUIDANCE = {
    "BraveSearchAuthenticationError": (
        "Authentication rejected (HTTP 401). Create a key under Brave's Search plan; do "
        "not substitute an Answers-only key."
    ),
    "BraveSearchPlanError": (
        "Search-product access denied (HTTP 402/403). Check the Search subscription, "
        "billing, and credits in Brave's dashboard."
    ),
    "BraveSearchRateLimitError": (
        "Search rate or credit limit reached (HTTP 429). Check Brave usage before retrying."
    ),
    "BraveSearchRequestError": (
        "Brave rejected the Web Search request. Run the dedicated Search probe."
    ),
    "BraveSearchUnavailableError": (
        "Brave Web Search was unreachable or unavailable. Retry the Search probe later."
    ),
    "BraveSearchResponseError": (
        "Brave returned an unexpected Web Search response. Run the Search probe and "
        "check provider status."
    ),
}


def brave_search_failure_guidance(error_types: list[str]) -> str | None:
    """Return actionable copy from metadata-only exception class names."""

    for error_type in error_types:
        guidance = _FAILURE_GUIDANCE.get(error_type)
        if guidance is not None:
            return guidance
    return None
