from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from betteroption.discovery import DiscoveredJob, DiscoveryQuery
from betteroption.discovery_sources import DiscoverySourceMesh
from betteroption.jobs import JobPosting, JobSourceType, JobUrlStatus
from betteroption.matching import (
    SOLID_MATCH_CALIBRATION_CAP,
    MatchResult,
    match_job,
    solid_match_calibration_bonus,
)
from betteroption.profile import CandidateProfile


class StaticDiscoveryProvider:
    name = "static"
    attribution = "Static test source"
    attribution_url = "https://example.com/source"

    def __init__(self, count: int) -> None:
        self.jobs = [
            DiscoveredJob(
                provider="arbeitnow",
                external_id=str(index),
                title=f"Embedded Engineer {index}",
                company=f"Employer {index}",
                location="Berlin",
                summary="Embedded product development.",
                source_url=f"https://careers{index}.example/jobs/{index}",
            )
            for index in range(count)
        ]

    def search(self, query: DiscoveryQuery) -> list[DiscoveredJob]:
        return self.jobs


def test_explore_defaults_to_and_accepts_an_explicit_300_result_limit() -> None:
    assert DiscoveryQuery(text="embedded").limit == 300
    assert DiscoveryQuery(text="embedded", limit=300).limit == 300
    with pytest.raises(ValidationError):
        DiscoveryQuery(text="embedded", limit=301)

    mesh = DiscoverySourceMesh(
        [StaticDiscoveryProvider(300)],
        search_budget_seconds=999,
    )

    assert len(mesh.search(DiscoveryQuery(text="embedded", limit=300))) == 300
    # Explore deliberately allows careful multi-provider work for up to seven minutes.
    assert mesh.search_budget_seconds == 420.0


def test_manual_text_with_reference_url_matches_without_forged_verification() -> None:
    job = JobPosting(
        title="Embedded Engineer",
        company="Example Products",
        location="Berlin",
        summary="Develop embedded products.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name="https://careers.example/jobs/embedded",
        source_url="https://careers.example/jobs/embedded",
        requested_url="https://careers.example/jobs/embedded",
        source_text="Develop embedded products.",
    )

    result = match_job(CandidateProfile(), job)
    restored = MatchResult.model_validate_json(result.model_dump_json())

    assert restored.source_is_manual is True
    assert str(restored.job_url) == "https://careers.example/jobs/embedded"
    assert restored.url_status is None
    assert restored.url_http_status is None
    assert restored.url_verified_at is None

    forged = result.model_dump()
    forged.update(
        {
            "url_status": JobUrlStatus.VERIFIED_REACHABLE,
            "url_http_status": 200,
            "url_verified_at": datetime.now(timezone.utc),
        }
    )
    with pytest.raises(ValidationError, match="manual match cannot claim URL verification"):
        MatchResult.model_validate(forged)


def test_positive_fit_calibration_is_slightly_stricter_and_still_bounded() -> None:
    assert SOLID_MATCH_CALIBRATION_CAP == 3
    assert (
        solid_match_calibration_bonus(
            satisfied_hard_requirements=10,
            supporting_preferences=10,
            matched_required_skills=10,
            hard_violations=0,
            violated_exclusion=False,
        )
        == 3
    )
    assert (
        solid_match_calibration_bonus(
            satisfied_hard_requirements=10,
            supporting_preferences=10,
            matched_required_skills=10,
            hard_violations=1,
            violated_exclusion=False,
        )
        == 0
    )
