from __future__ import annotations

import socket
import ssl
from collections.abc import Callable

import httpx
import pytest

import betteroption.providers.openwebninja_jsearch as provider_module
from betteroption.discovery import DiscoveryQuery
from betteroption.jsearch_diagnostics import (
    JSearchDiagnosticCategory,
    check_jsearch_access,
)
from betteroption.providers.openwebninja_jsearch import (
    JSearchProxyError,
    OpenWebNinjaJSearchProvider,
)
from betteroption.settings import Settings


SECRET = "v072a-jsearch-secret-must-not-appear"
TRANSPORT_CANARY = "private-low-level-transport-detail"


def _settings() -> Settings:
    return Settings(
        OPENWEBNINJA_JSEARCH_API_KEY=SECRET,
        database_url="sqlite:///:memory:",
        _env_file=None,
    )


def _success_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "OK",
            "data": {
                "jobs": [
                    {
                        "job_id": "diagnostic-result",
                        "job_title": "Software Developer",
                        "employer_name": "Example Employer",
                        "job_apply_link": "https://jobs.example.test/developer",
                    }
                ],
                "cursor": None,
            },
        },
    )


def _transport_handler(kind: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if kind == "read_timeout":
            raise httpx.ReadTimeout(TRANSPORT_CANARY, request=request)
        if kind == "connect_timeout":
            raise httpx.ConnectTimeout(TRANSPORT_CANARY, request=request)
        if kind == "write_timeout":
            raise httpx.WriteTimeout(TRANSPORT_CANARY, request=request)
        if kind == "pool_timeout":
            raise httpx.PoolTimeout(TRANSPORT_CANARY, request=request)
        if kind == "proxy":
            raise httpx.ProxyError(TRANSPORT_CANARY, request=request)
        if kind == "dns":
            try:
                raise socket.gaierror(socket.EAI_NONAME, TRANSPORT_CANARY)
            except socket.gaierror as error:
                raise httpx.ConnectError(TRANSPORT_CANARY, request=request) from error
        if kind == "tls":
            try:
                raise ssl.SSLCertVerificationError(1, TRANSPORT_CANARY)
            except ssl.SSLError as error:
                raise httpx.ConnectError(TRANSPORT_CANARY, request=request) from error
        raise httpx.ConnectError(TRANSPORT_CANARY, request=request)

    return handler


@pytest.mark.parametrize(
    ("kind", "category"),
    [
        ("connect_timeout", JSearchDiagnosticCategory.CONNECT_TIMEOUT),
        ("read_timeout", JSearchDiagnosticCategory.READ_TIMEOUT),
        ("write_timeout", JSearchDiagnosticCategory.WRITE_TIMEOUT),
        ("pool_timeout", JSearchDiagnosticCategory.POOL_TIMEOUT),
        ("dns", JSearchDiagnosticCategory.DNS),
        ("tls", JSearchDiagnosticCategory.TLS),
        ("proxy", JSearchDiagnosticCategory.PROXY),
        ("connection", JSearchDiagnosticCategory.CONNECTION),
    ],
)
def test_v072a_diagnostic_classifies_transport_failures_without_leaking_details(
    kind: str,
    category: JSearchDiagnosticCategory,
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(_transport_handler(kind)))

    diagnostic = check_jsearch_access(_settings(), client=client)

    assert diagnostic.category is category
    assert diagnostic.result_count == 0
    assert TRANSPORT_CANARY not in repr(diagnostic)
    assert TRANSPORT_CANARY not in diagnostic.detail
    assert TRANSPORT_CANARY not in diagnostic.next_step
    assert SECRET not in repr(diagnostic)


@pytest.mark.parametrize("status_code", [500, 503, 599])
def test_v072a_http_5xx_is_provider_unavailable_not_a_local_network_failure(
    status_code: int,
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, text=TRANSPORT_CANARY)
        )
    )

    diagnostic = check_jsearch_access(_settings(), client=client)

    assert diagnostic.category is JSearchDiagnosticCategory.PROVIDER_UNAVAILABLE
    assert "provider-side HTTP 5xx" in diagnostic.detail
    assert "local connection worked" in diagnostic.next_step
    assert TRANSPORT_CANARY not in repr(diagnostic)


def test_v072a_provider_created_client_respects_proxy_and_certificate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_kwargs: list[dict[str, object]] = []
    client = httpx.Client(transport=httpx.MockTransport(_success_response))

    def client_factory(**kwargs: object) -> httpx.Client:
        created_kwargs.append(kwargs)
        return client

    monkeypatch.setattr(provider_module.httpx, "Client", client_factory)

    provider = OpenWebNinjaJSearchProvider("key", max_requests=1)
    jobs = provider.search(DiscoveryQuery(text="software developer"))

    assert len(jobs) == 1
    assert created_kwargs[0]["trust_env"] is True


def test_v072a_diagnostic_created_client_respects_environment_and_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_kwargs: list[dict[str, object]] = []
    client = httpx.Client(transport=httpx.MockTransport(_success_response))

    def client_factory(**kwargs: object) -> httpx.Client:
        created_kwargs.append(kwargs)
        return client

    monkeypatch.setattr(provider_module.httpx, "Client", client_factory)

    diagnostic = check_jsearch_access(_settings())

    assert diagnostic.category is JSearchDiagnosticCategory.SUCCESS
    assert created_kwargs[0]["trust_env"] is True
    timeout = created_kwargs[0]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10.0
    assert timeout.read == 90.0
    assert timeout.write == 10.0
    assert timeout.pool == 5.0
    assert client.is_closed is True


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (ImportError(TRANSPORT_CANARY), JSearchDiagnosticCategory.PROXY),
        (ValueError(TRANSPORT_CANARY), JSearchDiagnosticCategory.PROXY),
        (FileNotFoundError(TRANSPORT_CANARY), JSearchDiagnosticCategory.TLS),
    ],
)
def test_v072a_diagnostic_classifies_environment_failure_before_request(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    category: JSearchDiagnosticCategory,
) -> None:
    def client_factory(**_kwargs: object) -> httpx.Client:
        raise error

    monkeypatch.setattr(provider_module.httpx, "Client", client_factory)

    diagnostic = check_jsearch_access(_settings())

    assert diagnostic.category is category
    assert TRANSPORT_CANARY not in repr(diagnostic)
    assert TRANSPORT_CANARY not in diagnostic.detail
    assert TRANSPORT_CANARY not in diagnostic.next_step


def test_v072a_optional_provider_does_not_fail_application_construction_for_socks_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def client_factory(**_kwargs: object) -> httpx.Client:
        raise ImportError(TRANSPORT_CANARY)

    monkeypatch.setattr(provider_module.httpx, "Client", client_factory)

    provider = OpenWebNinjaJSearchProvider("key", max_requests=1)

    with pytest.raises(JSearchProxyError) as caught:
        provider.search(DiscoveryQuery(text="software developer"))
    assert TRANSPORT_CANARY not in str(caught.value)
