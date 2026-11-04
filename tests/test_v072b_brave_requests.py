from __future__ import annotations

from threading import Lock

import httpx

from betteroption.discovery import BraveWebDiscoveryProvider, DiscoveryQuery


def _recording_provider() -> tuple[BraveWebDiscoveryProvider, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    lock = Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            requests.append(request)
        return httpx.Response(200, request=request, json={"web": {"results": []}})

    return (
        BraveWebDiscoveryProvider(
            "search-plan-key",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        requests,
    )


def test_brave_uses_german_market_parameters_and_coarse_offline_postcode_headers() -> None:
    provider, requests = _recording_provider()

    provider.search(
        DiscoveryQuery(
            text="software developer",
            location="60486",
            desired_terms=["software developer"],
        )
    )

    assert requests
    queries = {request.url.params["q"] for request in requests}
    assert any('"software developer"' in query for query in queries)
    assert any('"softwareentwickler"' in query for query in queries)
    for request in requests:
        assert request.url.path == "/res/v1/web/search"
        assert request.url.params["country"] == "DE"
        expected_language = (
            "de" if "softwareentwickler" in request.url.params["q"].casefold() else "en"
        )
        assert request.url.params["search_lang"] == expected_language
        assert request.url.params["ui_lang"] == "de-DE"
        assert request.url.params["units"] == "metric"
        assert request.url.params["extra_snippets"] == "true"
        assert "freshness" not in request.url.params
        assert request.url.params["offset"] == "0"
        assert request.headers["X-Subscription-Token"] == "search-plan-key"
        assert request.headers["X-Loc-Lat"] == "50.12"
        assert request.headers["X-Loc-Long"] == "8.64"
        assert request.headers["X-Loc-Country"] == "DE"
        assert request.headers["X-Loc-City"] == "Frankfurt am Main"
        assert request.headers["X-Loc-Postal-Code"] == "60486"
        assert "X-Loc-State" not in request.headers
        assert "X-Loc-State-Name" not in request.headers


def test_brave_city_origin_does_not_invent_postcode_or_state_headers() -> None:
    provider, requests = _recording_provider()

    provider.search(DiscoveryQuery(text="embedded engineer", location="Berlin"))

    assert requests
    for request in requests:
        local_headers = {
            key.casefold(): value
            for key, value in request.headers.items()
            if key.casefold().startswith("x-loc-")
        }
        assert local_headers == {
            "x-loc-lat": "52.52",
            "x-loc-long": "13.41",
            "x-loc-country": "DE",
            "x-loc-city": "Berlin",
        }


def test_brave_uses_english_for_non_developer_english_role_queries() -> None:
    provider, requests = _recording_provider()

    provider.search(
        DiscoveryQuery(
            text="quality assurance specialist",
            desired_terms=["quality assurance specialist"],
            location="Berlin",
        )
    )

    focused = [
        request
        for request in requests
        if '"quality assurance specialist"' in request.url.params["q"].casefold()
    ]
    assert focused
    assert all(request.url.params["search_lang"] == "en" for request in focused)


def test_brave_unresolved_origin_uses_safe_market_defaults_without_location_headers() -> None:
    provider, requests = _recording_provider()

    provider.search(
        DiscoveryQuery(
            text="embedded engineer",
            location="Place That Cannot Resolve 987654321",
        )
    )

    assert requests
    for request in requests:
        assert request.url.params["search_lang"] in {"de", "en"}
        assert request.url.params["ui_lang"] == "en-US"
        assert request.url.params["units"] == "metric"
        assert request.url.params["extra_snippets"] == "true"
        assert "country" not in request.url.params
        assert not any(key.casefold().startswith("x-loc-") for key in request.headers)


def test_brave_worldwide_search_does_not_apply_local_country_or_location_bias() -> None:
    provider, requests = _recording_provider()

    provider.search(
        DiscoveryQuery(
            text="embedded engineer",
            location="Berlin",
            worldwide=True,
        )
    )

    assert requests
    for request in requests:
        assert request.url.params["search_lang"] in {"de", "en"}
        assert request.url.params["ui_lang"] == "de-DE"
        assert "country" not in request.url.params
        assert not any(key.casefold().startswith("x-loc-") for key in request.headers)


def test_brave_requests_page_two_only_when_the_response_advertises_more_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        has_more = request.url.params["offset"] == "0"
        return httpx.Response(
            200,
            request=request,
            json={
                "query": {"more_results_available": has_more},
                "web": {"results": []},
            },
        )

    provider = BraveWebDiscoveryProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    query = DiscoveryQuery(text="python developer", location="Berlin")

    assert provider.search(query) == []
    assert sum(request.url.params["offset"] == "1" for request in requests) == 1
    assert provider.last_request_count == len(requests)
    assert provider.last_request_count == provider.maximum_request_count(query)


def test_brave_uses_extra_snippets_as_job_evidence_and_result_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Python Developer Job in Berlin",
                            "url": "https://careers.acme.example/jobs/python-berlin",
                            "description": "",
                            "extra_snippets": [
                                "Python developer vacancy in Berlin building web services."
                            ],
                        }
                    ]
                }
            },
        )

    provider = BraveWebDiscoveryProvider(
        "key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    jobs = provider.search(DiscoveryQuery(text="python developer", location="Berlin"))

    assert jobs
    assert "Python developer vacancy in Berlin" in jobs[0].summary
