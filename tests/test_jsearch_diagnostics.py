from __future__ import annotations

import httpx
import pytest

from betteroption.jsearch_diagnostics import (
    JSearchDiagnostic,
    JSearchDiagnosticCategory,
    check_jsearch_access,
)
from betteroption.settings import Settings
from scripts import diagnose_jsearch


SECRET = "diagnostic-secret-that-must-never-appear"


def _settings(key: str | None = SECRET) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "database_url": "sqlite:///:memory:",
    }
    if key is not None:
        values["OPENWEBNINJA_JSEARCH_API_KEY"] = key
    return Settings(**values)


def _job_row() -> dict[str, object]:
    return {
        "job_id": "diagnostic-result",
        "job_title": "Software Developer",
        "employer_name": "Example Employer",
        "job_apply_link": "https://jobs.example.test/software-developer",
        "job_location": "Berlin, Germany",
    }


def _client(
    handler,
) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_jsearch_live_diagnostic_succeeds_with_exactly_one_secret_safe_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": "OK", "data": {"jobs": [_job_row()], "cursor": None}},
        )

    diagnostic = check_jsearch_access(_settings(), client=_client(handler))

    assert diagnostic.category is JSearchDiagnosticCategory.SUCCESS
    assert diagnostic.result_count == 1
    assert diagnostic.success is True
    assert len(requests) == 1
    assert requests[0].headers["X-API-Key"] == SECRET
    assert SECRET not in str(requests[0].url)
    assert SECRET not in repr(diagnostic)
    assert set(vars(diagnostic)) == {"category", "result_count"}


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (401, JSearchDiagnosticCategory.AUTHENTICATION),
        (402, JSearchDiagnosticCategory.PLAN),
        (403, JSearchDiagnosticCategory.PLAN),
        (429, JSearchDiagnosticCategory.RATE_LIMIT),
        (400, JSearchDiagnosticCategory.REQUEST),
        (503, JSearchDiagnosticCategory.PROVIDER_UNAVAILABLE),
    ],
)
def test_jsearch_live_diagnostic_maps_http_failures_without_exposing_response(
    status_code: int,
    category: JSearchDiagnosticCategory,
) -> None:
    requests: list[httpx.Request] = []
    response_canary = "provider-body-must-never-appear"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, text=response_canary)

    diagnostic = check_jsearch_access(_settings(), client=_client(handler))

    assert diagnostic.category is category
    assert diagnostic.result_count == 0
    assert len(requests) == 1
    assert SECRET not in repr(diagnostic)
    assert response_canary not in repr(diagnostic)


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        (
            {"status": "ERROR", "error": {"code": "rate_limit_exceeded"}},
            JSearchDiagnosticCategory.RATE_LIMIT,
        ),
        (
            {"status": "ERROR", "error": {"message": "opaque-provider-detail"}},
            JSearchDiagnosticCategory.RESPONSE,
        ),
        (
            {"status": "OK", "data": {"jobs": {"not": "a-list"}}},
            JSearchDiagnosticCategory.RESPONSE,
        ),
    ],
)
def test_jsearch_diagnostic_distinguishes_safe_envelope_failures(
    payload: dict[str, object],
    category: JSearchDiagnosticCategory,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=payload)

    diagnostic = check_jsearch_access(_settings(), client=_client(handler))

    assert diagnostic.category is category
    assert "opaque-provider-detail" not in repr(diagnostic)
    assert "opaque-provider-detail" not in diagnostic.detail
    assert SECRET not in diagnostic.next_step
    assert "http" not in diagnostic.next_step.casefold()


def test_jsearch_live_diagnostic_maps_network_failure_without_retry_or_exception_text() -> None:
    requests: list[httpx.Request] = []
    network_canary = "network-detail-must-never-appear"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError(network_canary, request=request)

    diagnostic = check_jsearch_access(_settings(), client=_client(handler))

    assert diagnostic.category is JSearchDiagnosticCategory.CONNECTION
    assert diagnostic.result_count == 0
    assert len(requests) == 1
    assert network_canary not in repr(diagnostic)


def test_jsearch_live_diagnostic_does_not_request_without_a_configured_key() -> None:
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, json={"data": []})

    diagnostic = check_jsearch_access(_settings(None), client=_client(handler))

    assert diagnostic.category is JSearchDiagnosticCategory.NOT_CONFIGURED
    assert diagnostic.result_count == 0
    assert requested is False


def test_jsearch_cli_requires_live_opt_in_and_prints_only_fixed_safe_guidance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def fail_if_called(_settings: Settings):
        nonlocal called
        called = True
        raise AssertionError("probe must not run without --live")

    monkeypatch.setattr(diagnose_jsearch, "check_jsearch_access", fail_if_called)

    assert diagnose_jsearch.main([]) == 2
    assert capsys.readouterr().out.splitlines() == [
        "category: not_run",
        "result_count: 0",
        "detail: The live provider probe was not authorized.",
        "next_step: Rerun with --live to authorize exactly one synthetic request.",
    ]
    assert called is False


def test_jsearch_cli_prints_actionable_sanitized_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        diagnose_jsearch,
        "check_jsearch_access",
        lambda _settings: JSearchDiagnostic(JSearchDiagnosticCategory.RESPONSE, 0),
    )

    assert diagnose_jsearch.main(["--live"]) == 1
    output = capsys.readouterr().out
    assert output.splitlines() == [
        "category: response",
        "result_count: 0",
        "detail: JSearch returned JSON that did not match a supported success envelope.",
        "next_step: Retest with the latest BetterOption release; if it persists, report this category.",
    ]
    assert SECRET not in output
    assert "software developer" not in output
