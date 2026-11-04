from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.cv import CvRetention
from betteroption.discovery import ArbeitnowDiscoveryProvider, DiscoveredJob, DiscoveryQuery
from betteroption.extraction import ExtractedFactDraft, SectionExtraction
from betteroption.job_extraction import JobExtraction, JobFactDraft
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.matching import MatchOutcome, match_job
from betteroption.mobility import (
    CommuteStatus,
    FallbackTravelTimeProvider,
    TransitousTravelTimeProvider,
    TravelQuery,
)
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelMode,
)
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


NOW = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)


class CvExtractor:
    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        assert section == ProfileSection.EXPERIENCE
        assert "Python" in user_text
        return SectionExtraction(
            summary="Candidate evidence found.",
            facts=[
                ExtractedFactDraft(
                    key="skill.experience",
                    value="Python",
                    level=RequirementLevel.OPEN,
                    evidence_status="explicit",
                    confidence=Confidence.HIGH,
                    source_quote="Python",
                )
            ],
            follow_up_question=None,
        )


class FixedDiscoveryProvider:
    name = "fixed"
    attribution = "Fixed test feed"
    attribution_url = "https://feed.example/api"

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        assert query.text == "embedded"
        return [
            DiscoveredJob(
                provider=self.name,
                external_id="job-1",
                title="Embedded Software Engineer",
                company="Warm Systems",
                location="Frankfurt",
                remote=True,
                tags=["C++", "Embedded"],
                summary="Build calm, useful products.",
                source_url="https://careers.example/jobs/1",
                published_at=NOW,
            )
        ]


class FixedJobFetcher:
    def fetch(self, url: str) -> FetchedDocument:
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            text="Warm Systems needs C++ for an Embedded Software Engineer role in Frankfurt.",
            fetched_at=NOW,
        )


class FixedJobExtractor:
    model = "fixed-job-model"

    def extract(self, source_text: str, **metadata):
        return JobExtraction(
            title="Embedded Software Engineer",
            company="Warm Systems",
            location="Frankfurt",
            summary="Build embedded products.",
            facts=[
                JobFactDraft(
                    key="skill.name",
                    value="C++",
                    kind="requirement",
                    evidence_quote="C++",
                )
            ],
        ).to_job_posting(source_text=source_text, **metadata)


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v067b.db').as_posix()}",
            employer_homepage_research=False,
            google_routes_api_key=None,
            openrouteservice_api_key=None,
            mobility_provider="auto",
            mobility_privacy_mode="privacy_first",
            _env_file=None,
        )
    )


def _salary_profile() -> CandidateProfile:
    return CandidateProfile(
        facts=[
            ProfileFact(
                key="compensation.minimum",
                value="€65,000",
                level=RequirementLevel.MUST_HAVE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.MUST_HAVES,
                    text="At least €65,000",
                ),
            )
        ]
    )


def _software_job(*, with_salary: bool = False) -> JobPosting:
    facts = (
        [
            JobFact(
                key="compensation.annual_gross",
                value="€70,000–€80,000",
                kind=JobFactKind.OFFER,
                evidence_quote="Salary €70,000–€80,000",
            )
        ]
        if with_salary
        else []
    )
    return JobPosting(
        title="Embedded Software Engineer",
        company="Acme",
        location="Frankfurt, Germany",
        summary="Develop embedded software products.",
        source_type=JobSourceType.SAMPLE,
        source_name="https://acme.example/jobs/1",
        source_text="Embedded software role. " + ("Salary €70,000–€80,000." if with_salary else ""),
        facts=facts,
    )


def test_transitous_geocodes_and_returns_a_keyless_transit_estimate() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/geocode"):
            is_origin = "Frankfurt" in str(request.url)
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "name": "Frankfurt am Main" if is_origin else "Darmstadt",
                        "country": "DE",
                        "lat": 50.11 if is_origin else 49.87,
                        "lon": 8.68 if is_origin else 8.65,
                    }
                ],
            )
        return httpx.Response(
            200,
            request=request,
            json={"itineraries": [{"duration": 2_460}]},
        )

    provider = TransitousTravelTimeProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    estimate = provider.estimate(
        TravelQuery(
            origin="Frankfurt",
            destination="Darmstadt",
            mode=TravelMode.TRANSIT,
            departure_at=NOW,
        )
    )

    assert estimate.status == CommuteStatus.AVAILABLE
    assert estimate.duration_minutes == 41
    assert estimate.provider == "transitous"
    assert estimate.cache_ttl_seconds == 43_200
    assert "Transitous" in (estimate.attribution or "")
    assert calls[-1].url.path == "/api/v6/plan"
    assert calls[-1].url.params["fromPlace"] == "50.11,8.68"
    assert calls[-1].headers["User-Agent"].startswith("BetterOption/")


def test_auto_mobility_has_privacy_providers_without_api_keys(tmp_path: Path) -> None:
    provider = _container(tmp_path).travel_time_provider()
    assert isinstance(provider, FallbackTravelTimeProvider)
    assert [candidate.name for candidate in provider.providers] == [
        "transitous",
        "valhalla-osm",
    ]


def test_legacy_cv_text_cannot_bypass_the_new_preview_action(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create()
    document = container.cvs.save(
        workspace.id,
        "resume.txt",
        "text/plain",
        b"Python engineer with embedded development and test automation experience.",
        CvRetention.UNTIL_DELETED,
    )
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            profile_extractor=CvExtractor(),
        )
    )

    compass = client.get(f"/profile/{workspace.id}")
    response = client.post(
        f"/profile/{workspace.id}/cv/{document.id}/review",
        follow_redirects=False,
    )

    assert "Legacy saved CV text exists" in compass.text
    assert "Delete CV text" in compass.text
    assert "Review and merge into Compass" not in compass.text
    assert response.status_code == 303
    assert "Direct+processing+of+legacy+saved+CV+text+is+disabled" in response.headers["location"]
    saved = container.workspaces.get(workspace.id)
    assert saved is not None
    assert not saved.session.profile.pending_facts
    assert not saved.session.profile.confirmed_facts


def test_explore_search_is_a_separate_non_mutating_page(tmp_path: Path) -> None:
    container = _container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=FixedDiscoveryProvider(),
        )
    )

    page = client.get("/explore?q=embedded&location=Frankfurt")

    assert page.status_code == 200
    assert "Embedded Software Engineer" in page.text
    assert "Save to Archive" in page.text
    assert "Save and run Match" in page.text
    assert 'name="selected_urls"' in page.text
    assert container.repository.count_records() == 0
    nav = "".join(page.text.split())
    assert nav.index(">Home</a>") < nav.index(">Compass</a>")
    assert nav.index(">Compass</a>") < nav.index(">Explore</a>")
    assert nav.index(">Explore</a>") < nav.index(">Match</a>")
    assert nav.index(">Match</a>") < nav.index(">Archive</a>")


def test_explore_selection_is_verified_before_archive_persistence(tmp_path: Path) -> None:
    container = _container(tmp_path)
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=FixedDiscoveryProvider(),
            job_fetcher=FixedJobFetcher(),
            job_extractor=FixedJobExtractor(),
        )
    )

    response = client.post(
        "/explore/save",
        data={
            "selected_urls": "https://careers.example/jobs/1",
            "destination": "archive",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs?notice=")
    assert container.repository.count_records() == 1
    record = container.repository.list_records()[0]
    assert record.last_http_status == 200
    assert container.repository.get_current_job(record.id) is not None


def test_arbeitnow_search_filters_and_deduplicates_public_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "slug": "embedded-1",
                        "title": "Embedded Software Engineer",
                        "company_name": "Acme",
                        "location": "Frankfurt",
                        "remote": True,
                        "tags": ["C++"],
                        "job_types": ["full-time"],
                        "description": "<p>Develop embedded products.</p>",
                        "url": "https://www.arbeitnow.com/jobs/embedded-1",
                        "created_at": 1_768_000_000,
                    }
                ]
            },
        )

    provider = ArbeitnowDiscoveryProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    jobs = provider.search(
        DiscoveryQuery(text="embedded C++", location="Frankfurt", remote_only=True)
    )

    assert len(jobs) == 1
    assert jobs[0].summary == "Develop embedded products."
    assert str(jobs[0].source_url).startswith("https://www.arbeitnow.com/")


def test_missing_advertised_salary_abstains_without_researched_evidence() -> None:
    result = match_job(_salary_profile(), _software_job())

    assert result.salary_estimate is None
    reason = next(
        reason for reason in result.reasons if reason.profile_key == "compensation.minimum"
    )
    assert reason.outcome == MatchOutcome.UNKNOWN
    assert reason.evidence_urls == []


def test_explicit_advertised_salary_wins_over_estimation() -> None:
    result = match_job(_salary_profile(), _software_job(with_salary=True))

    assert result.salary_estimate is None
    reason = next(
        reason for reason in result.reasons if reason.profile_key == "compensation.minimum"
    )
    assert reason.outcome == MatchOutcome.SATISFIED
