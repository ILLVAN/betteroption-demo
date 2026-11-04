import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.job_extraction import JobExtraction, JobFactDraft  # noqa: E402
from betteroption.jobs import (  # noqa: E402
    JobFact,
    JobPosting,
    JobSourceType,
    JobUrlStatus,
    load_job,
    save_job,
)
from betteroption.matching import MatchDisposition, MatchOutcome, match_jobs  # noqa: E402
from betteroption.profile import (  # noqa: E402
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.providers.openai_job import OpenAIJobExtractor  # noqa: E402
from examples.job_match_demo import print_result  # noqa: E402


SAMPLE_DIRECTORY = Path(__file__).parents[1] / "examples" / "sample_jobs"
VERIFIED_AT = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
JOB_URL = "https://example.com/jobs/embedded-engineer"


def extraction_arguments() -> dict:
    return {
        "source_name": JOB_URL,
        "source_url": JOB_URL,
        "requested_url": JOB_URL,
        "url_http_status": 200,
        "url_checked_at": VERIFIED_AT,
    }


def confirmed_fact(
    key: str,
    value: str,
    level: RequirementLevel,
    *,
    section: ProfileSection = ProfileSection.DIRECTION,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def matching_profile() -> CandidateProfile:
    return CandidateProfile(
        facts=[
            confirmed_fact("role.family", "embedded software", RequirementLevel.PREFERENCE),
            confirmed_fact("role.family", "FPGA development", RequirementLevel.PREFERENCE),
            confirmed_fact("role.responsibility", "prototyping", RequirementLevel.PREFERENCE),
            confirmed_fact(
                "work_model.hours_weekly",
                "30-40h",
                RequirementLevel.PREFERENCE,
            ),
            confirmed_fact(
                "compensation.minimum",
                "€55,000 per year",
                RequirementLevel.PREFERENCE,
            ),
            confirmed_fact(
                "work_model.office_days_max",
                "No more than three office days per week",
                RequirementLevel.MUST_HAVE,
            ),
            confirmed_fact(
                "work_model.remote",
                "Remote work otherwise",
                RequirementLevel.MUST_HAVE,
            ),
            confirmed_fact(
                "employment.arrangement",
                "Direct contract with the employer",
                RequirementLevel.MUST_HAVE,
            ),
            confirmed_fact(
                "employment.arrangement",
                "Temporary agency employment",
                RequirementLevel.EXCLUSION,
            ),
            confirmed_fact(
                "industry.desired",
                "defense or military",
                RequirementLevel.EXCLUSION,
            ),
            confirmed_fact(
                "work_model.shift_work",
                "No shift work",
                RequirementLevel.EXCLUSION,
            ),
            confirmed_fact(
                "skill.demonstrated",
                "C/C++",
                RequirementLevel.OPEN,
                section=ProfileSection.EXPERIENCE,
            ),
            confirmed_fact(
                "skill.demonstrated",
                "Python",
                RequirementLevel.OPEN,
                section=ProfileSection.EXPERIENCE,
            ),
            confirmed_fact(
                "skill.demonstrated",
                "FPGA",
                RequirementLevel.OPEN,
                section=ProfileSection.EXPERIENCE,
            ),
        ]
    )


class TestJobModel:
    def test_all_canonical_samples_have_verbatim_evidence(self) -> None:
        jobs = [load_job(path) for path in SAMPLE_DIRECTORY.glob("*.json")]

        assert len(jobs) == 4
        assert all(job.content_hash for job in jobs)

    def test_job_rejects_evidence_not_found_in_source(self) -> None:
        payload = load_job(SAMPLE_DIRECTORY / "embedded_prototyping.json").model_dump()
        payload["facts"][0]["evidence_quote"] = "This quote was invented"

        with pytest.raises(ValidationError):
            JobPosting.model_validate(payload)

    def test_job_round_trips_through_local_json(self) -> None:
        job = load_job(SAMPLE_DIRECTORY / "fpga_research.json")
        with TemporaryDirectory() as directory:
            path = save_job(job, Path(directory))
            restored = load_job(path)

        assert restored.id == job.id
        assert restored.content_hash == job.content_hash

    def test_real_job_requires_verified_reachable_url_metadata(self) -> None:
        payload = load_job(SAMPLE_DIRECTORY / "embedded_prototyping.json").model_dump()
        payload["source_type"] = JobSourceType.URL_TEXT

        with pytest.raises(ValidationError, match="requested_url and source_url"):
            JobPosting.model_validate(payload)


class FakeResponses:
    def __init__(self, *results: JobExtraction) -> None:
        self.results = list(results)
        self.call = None
        self.calls = []

    def parse(self, **kwargs):
        self.call = kwargs
        self.calls.append(kwargs)
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        return SimpleNamespace(output_parsed=result)


class TestJobExtraction:
    def test_provider_returns_job_with_verified_evidence(self) -> None:
        source = "Acme needs Python for an Embedded Engineer in Frankfurt."
        extraction = JobExtraction(
            title="Embedded Engineer",
            company="Acme",
            location="Frankfurt",
            summary="Embedded role requiring Python.",
            facts=[
                JobFactDraft(
                    key="skill.name",
                    value="Python",
                    kind="requirement",
                    evidence_quote="Python",
                )
            ],
        )
        responses = FakeResponses(extraction)
        provider = OpenAIJobExtractor(
            model="test-model",
            client=SimpleNamespace(responses=responses),
        )

        job = provider.extract(source, **extraction_arguments())

        assert job.title == "Embedded Engineer"
        assert job.facts[0].value == "Python"
        assert str(job.source_url) == JOB_URL
        assert job.url_status == JobUrlStatus.VERIFIED_REACHABLE
        assert "<job_advertisement>" in responses.call["input"][1]["content"]
        assert responses.call["text_format"] is JobExtraction

    def test_provider_rejects_empty_source_without_api_call(self) -> None:
        responses = FakeResponses(
            JobExtraction(
                title="Unknown",
                company="Unknown",
                location="Unknown",
                summary="Unknown job.",
                facts=[],
            )
        )
        provider = OpenAIJobExtractor(client=SimpleNamespace(responses=responses))

        with pytest.raises(ValueError):
            provider.extract(" ", **extraction_arguments())
        assert responses.call is None

    def test_normalizable_evidence_is_mapped_back_to_exact_source(self) -> None:
        source = "Acme offers hybrid\u00a0remote – work for embedded engineers."
        extraction = JobExtraction(
            title="Embedded Engineer",
            company="Acme",
            location="Remote",
            summary="Hybrid embedded role.",
            facts=[
                JobFactDraft(
                    key="work_model.remote",
                    value="hybrid remote",
                    kind="offer",
                    evidence_quote="hybrid remote - work",
                )
            ],
        )
        responses = FakeResponses(extraction)
        provider = OpenAIJobExtractor(client=SimpleNamespace(responses=responses))

        job = provider.extract(source, **extraction_arguments())

        assert job.facts[0].evidence_quote == "hybrid\u00a0remote – work"
        assert len(responses.calls) == 1

    def test_invalid_evidence_is_retried_with_diagnostics(self) -> None:
        source = "Acme requires Python for an embedded role."
        invalid = JobExtraction(
            title="Embedded Engineer",
            company="Acme",
            location="Frankfurt",
            summary="Embedded role.",
            facts=[
                JobFactDraft(
                    key="skill.name",
                    value="Python",
                    kind="requirement",
                    evidence_quote="advanced Python expertise",
                )
            ],
        )
        corrected = invalid.model_copy(deep=True)
        corrected.facts[0].evidence_quote = "requires Python"
        responses = FakeResponses(invalid, corrected)
        provider = OpenAIJobExtractor(client=SimpleNamespace(responses=responses))

        job = provider.extract(source, **extraction_arguments())

        assert job.facts[0].evidence_quote == "requires Python"
        assert len(responses.calls) == 2
        assert "Invalid proposals were" in responses.calls[1]["input"][1]["content"]

    def test_persistently_invalid_facts_are_omitted_not_used(self) -> None:
        source = "Acme is hiring an embedded engineer in Frankfurt."
        invalid = JobExtraction(
            title="Embedded Engineer",
            company="Acme",
            location="Frankfurt",
            summary="Embedded role.",
            facts=[
                JobFactDraft(
                    key="compensation.annual_gross",
                    value="EUR 90,000",
                    kind="offer",
                    evidence_quote="EUR 90,000",
                )
            ],
        )
        responses = FakeResponses(invalid, invalid)
        provider = OpenAIJobExtractor(client=SimpleNamespace(responses=responses))

        job = provider.extract(source, **extraction_arguments())

        assert job.facts == []
        assert len(job.extraction_warnings) == 1
        assert "compensation.annual_gross" in job.extraction_warnings[0]


class TestDeterministicMatching:
    def test_sample_jobs_cover_ranked_and_blocked_results(self) -> None:
        jobs = [load_job(path) for path in SAMPLE_DIRECTORY.glob("*.json")]

        run = match_jobs(matching_profile(), jobs)
        results_by_title = {
            next(job.title for job in jobs if job.id == result.job_id): result
            for result in run.results
        }

        assert results_by_title["Embedded Prototyping Engineer"].disposition == MatchDisposition.TOP
        assert results_by_title["FPGA Research Engineer"].disposition == MatchDisposition.TOP
        assert (
            results_by_title["Test Automation Consultant"].disposition == MatchDisposition.BLOCKED
        )
        assert results_by_title["Test Automation Consultant"].hard_violations == 3
        agency_violations = [
            reason
            for reason in results_by_title["Test Automation Consultant"].reasons
            if reason.outcome == MatchOutcome.VIOLATED
        ]
        assert len(agency_violations) == 3
        assert results_by_title["FPGA Systems Developer"].disposition == MatchDisposition.BLOCKED

    def test_top_match_has_skill_and_source_evidence(self) -> None:
        job = load_job(SAMPLE_DIRECTORY / "embedded_prototyping.json")

        result = match_jobs(matching_profile(), [job]).results[0]

        assert result.disposition == MatchDisposition.TOP
        assert result.hard_evidence_coverage > 50
        assert set(result.matched_required_skills) == {"C++", "Python"}
        assert result.missing_required_skills == []
        assert any(reason.evidence_quotes for reason in result.reasons)
        supporting_keys = {
            reason.profile_key
            for reason in result.reasons
            if reason.outcome == MatchOutcome.SUPPORTING
        }
        assert "work_model.hours_weekly" in supporting_keys
        assert "compensation.minimum" in supporting_keys

    def test_alternative_skill_requirement_is_satisfied_by_one_option(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        source = "Knowledge of Rust, C, C++, or comparable programming language is required."
        job = JobPosting(
            title="Battery Software Engineer",
            company="Acme",
            location="Alzenau",
            summary="Battery systems software role.",
            source_type=JobSourceType.URL_TEXT,
            source_name=JOB_URL,
            source_url=JOB_URL,
            requested_url=JOB_URL,
            url_status=JobUrlStatus.VERIFIED_REACHABLE,
            url_http_status=200,
            url_checked_at=VERIFIED_AT,
            source_text=source,
            facts=[
                JobFact(
                    key="skill.name",
                    value="Rust, C, C++, or comparable programming language",
                    kind="requirement",
                    evidence_quote=source.removesuffix(" is required."),
                )
            ],
        )

        result = match_jobs(matching_profile(), [job]).results[0]

        assert result.missing_required_skills == []
        assert result.matched_required_skills == ["One of Rust / C / C++ (matched: C++)"]
        assert str(result.job_url) == JOB_URL
        assert result.url_http_status == 200

        print_result(1, job, result)
        output = capsys.readouterr().out
        assert f"Job URL: {JOB_URL}" in output
        assert "URL status: verified reachable (HTTP 200)" in output
