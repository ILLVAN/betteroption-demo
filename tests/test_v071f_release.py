"""Release identity and backward-compatibility checks retained by v0.7.2k."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from betteroption.llm import LLMTask
from betteroption.matching import MatchResult, MatchRun
from betteroption.result_repository import MatchRunRow
from betteroption.results import CURRENT_MATCHING_ALGORITHM
from betteroption.settings import Settings


ACTIVE_USER_AGENT_FILES = (
    Path(".env.example"),
    Path("src/betteroption/settings.py"),
    Path("src/betteroption/company_intelligence.py"),
    Path("src/betteroption/url_ingestion.py"),
    Path("src/betteroption/discovery.py"),
    Path("src/betteroption/discovery_sources.py"),
    Path("src/betteroption/mobility.py"),
    Path("src/betteroption/providers/apify_all_jobs.py"),
    Path("src/betteroption/providers/apify_eures.py"),
    Path("src/betteroption/providers/apify_jobspipe.py"),
    Path("src/betteroption/providers/openwebninja_jsearch.py"),
)


def test_candidate_control_invalidates_older_match_runs() -> None:
    run = MatchRun(profile_id=uuid4(), results=[])

    assert CURRENT_MATCHING_ALGORITHM == "matching-v0.7.2i"
    assert run.algorithm_version == CURRENT_MATCHING_ALGORITHM
    assert MatchRunRow.__table__.c.algorithm_version.default.arg == CURRENT_MATCHING_ALGORITHM
    assert "matching-v0.7.2" != CURRENT_MATCHING_ALGORITHM


def test_material_provider_notice_change_has_new_draft_versions() -> None:
    assert Settings.model_fields["legal_terms_version"].default == "2026-08-02-draft"
    assert Settings.model_fields["legal_privacy_version"].default == "2026-08-05-feedback-draft"


def test_active_outbound_user_agents_identify_v072k() -> None:
    for path in ACTIVE_USER_AGENT_FILES:
        text = path.read_text(encoding="utf-8")
        assert "BetterOption/0.7.2k" in text, path
        assert "BetterOption/0.7.1p-local-stability" not in text, path
        assert "BetterOption/0.7.1o-local-quality" not in text, path
        assert "BetterOption/0.7.1n-local-experience" not in text, path
        assert "BetterOption/0.7.1m-local-readiness" not in text, path
        assert "BetterOption/0.7.1i-evidence-workflow" not in text, path


def test_changed_prompts_have_o_versions() -> None:
    policy = Settings(database_url="sqlite:///:memory:").model_policy()

    assert policy.route(LLMTask.JOB_EXTRACTION).prompt_version == "job-v0.7.1o"
    assert policy.route(LLMTask.APPLICATION_DRAFT).prompt_version == "application-draft-v0.7.1o"
    assert policy.route(LLMTask.SALARY_RESEARCH).prompt_version == "salary-research-v0.7.1o"


def test_v071e_salary_snapshot_remains_readable() -> None:
    """Stored JSON from v0.7.1e must survive the salary-model generalisation."""

    result = MatchResult.model_validate(
        {
            "job_id": str(uuid4()),
            "score": 68,
            "hard_evidence_coverage": 50,
            "disposition": "top",
            "hard_violations": 0,
            "salary_estimate": {
                "occupation_family": "Software development",
                "annual_min_eur": 58_656,
                "annual_max_eur": 88_620,
                "confidence": "medium",
                "source_label": "Bundesagentur für Arbeit Entgeltatlas",
                "source_url": "https://web.arbeitsagentur.de/entgeltatlas/beruf/15260",
                "assumption": "Legacy v0.7.1e occupation benchmark.",
            },
        }
    )

    assert result.salary_estimate is not None
    assert result.salary_estimate.annual_min_eur == 58_656
    assert result.salary_estimate.source_label == "Bundesagentur für Arbeit Entgeltatlas"
