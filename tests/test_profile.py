import sys
from contextlib import chdir
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from betteroption.profile import (  # noqa: E402
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    ReferenceJob,
    SourceExcerpt,
    WorkModel,
    ReviewAction,
    RequirementLevel,
)
from betteroption.extraction import ExtractedFactDraft, SectionExtraction  # noqa: E402
from betteroption.providers.openai import (  # noqa: E402
    SECTION_INSTRUCTIONS,
    OpenAIProfileExtractor,
)
from betteroption.review import apply_review, merge_extracted_facts, save_profile  # noqa: E402
from betteroption.runtime import is_virtual_environment  # noqa: E402
from betteroption.session import (  # noqa: E402
    CORE_SECTION_DEFINITIONS,
    SectionStatus,
    SessionState,
    complete_section_review,
    latest_session_path,
    load_session,
    mark_section_skipped,
    new_session,
    next_pending_section,
    next_review_section,
    progress_for,
    record_section_extraction,
    reopen_skipped_sections,
    save_session,
)
from betteroption.terminal import edit_confirmed_profile, review_profile  # noqa: E402

from examples.profile_demo import build_demo_profile  # noqa: E402
from examples.profile_session import run_session  # noqa: E402


def stub_terminal(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
) -> None:
    answers = iter(responses)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: None)


class TestProfileProtocol:
    def test_inference_cannot_be_high_confidence(self) -> None:
        with pytest.raises(ValidationError):
            ProfileFact(
                key="role.family",
                value="software engineering",
                evidence_status=EvidenceStatus.INFERRED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.DIRECTION, text="closer to development"
                ),
            )

    def test_confirmed_fact_is_not_pending(self) -> None:
        fact = ProfileFact(
            key="salary.minimum_eur",
            value=65_000,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(section=ProfileSection.COMPENSATION_TIME, text="at least 65k"),
        )
        profile = CandidateProfile(facts=[fact])
        assert fact.needs_confirmation is False
        assert profile.confirmed_facts == [fact]

    def test_reference_learning_is_opt_in(self) -> None:
        with pytest.raises(ValidationError):
            ReferenceJob(url="https://example.com/job", learning_scope=["culture"])

    def test_reference_job_accepts_only_a_url_not_pasted_text(self) -> None:
        with pytest.raises(ValidationError):
            ReferenceJob.model_validate(
                {
                    "url": "https://example.com/job",
                    "pasted_text": "Copied advertisement text",
                }
            )
        with pytest.raises(ValidationError):
            ReferenceJob(url="Copied advertisement text")

    def test_reference_url_verification_metadata_must_be_complete(self) -> None:
        with pytest.raises(ValidationError, match="verification metadata"):
            ReferenceJob(
                url="https://example.com/job",
                resolved_url="https://example.com/jobs/123",
            )

        reference = ReferenceJob(
            url="https://example.com/job",
            resolved_url="https://example.com/jobs/123",
            url_http_status=200,
            url_verified_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        )
        assert reference.url_http_status == 200

    def test_working_hours_must_be_consistent(self) -> None:
        with pytest.raises(ValidationError):
            WorkModel(target_weekly_hours=40, maximum_weekly_hours=35)

    def test_demo_profile_is_valid_and_reviewable(self) -> None:
        profile = build_demo_profile()
        assert profile.protocol_version == "0.1"
        assert profile.compensation.minimum_gross_annual == 58_000
        assert len(profile.location.travel_constraints) == 2
        assert len(profile.pending_facts) == 7

    def test_candidate_evidence_is_separate_from_search_preferences(self) -> None:
        preference = ProfileFact(
            key="role.family",
            value="Embedded engineering",
            level="preference",
            evidence_status="confirmed",
            confidence="high",
            source=SourceExcerpt(
                section=ProfileSection.DIRECTION,
                text="embedded engineering",
            ),
        )
        evidence = ProfileFact(
            key="skill.demonstrated",
            value="C++",
            level="open",
            evidence_status="confirmed",
            confidence="high",
            source=SourceExcerpt(section=ProfileSection.EXPERIENCE, text="Strong in C++"),
        )
        profile = CandidateProfile(facts=[preference, evidence])

        assert profile.confirmed_search_facts == [preference]
        assert profile.confirmed_candidate_evidence == [evidence]


class FakeResponses:
    def __init__(self, result: SectionExtraction) -> None:
        self.result = result
        self.call = None

    def parse(self, **kwargs):
        self.call = kwargs
        return SimpleNamespace(output_parsed=self.result)


class TestOpenAIExtraction:
    def test_provider_returns_typed_reviewable_facts(self) -> None:
        result = SectionExtraction(
            summary="Engineering and test automation are preferred.",
            facts=[
                ExtractedFactDraft(
                    key="role.family",
                    value="Embedded engineering",
                    level="preference",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="closer to engineering, embedded",
                )
            ],
            follow_up_question=None,
        )
        responses = FakeResponses(result)
        client = SimpleNamespace(responses=responses)
        provider = OpenAIProfileExtractor(model="test-model", client=client)

        extraction = provider.extract(ProfileSection.DIRECTION, "Embedded would be good")
        facts = extraction.to_profile_facts(ProfileSection.DIRECTION)

        assert facts[0].key == "role.family"
        assert facts[0].needs_confirmation is True
        assert responses.call["model"] == "test-model"
        assert responses.call["text_format"] is SectionExtraction
        assert "<user_text>" in responses.call["input"][1]["content"]
        assert "industry.sector" in responses.call["input"][0]["content"]

    def test_provider_rejects_empty_input_without_api_call(self) -> None:
        result = SectionExtraction(
            summary="Empty", facts=[], follow_up_question="What are you looking for?"
        )
        responses = FakeResponses(result)
        provider = OpenAIProfileExtractor(client=SimpleNamespace(responses=responses))

        with pytest.raises(ValueError):
            provider.extract(ProfileSection.DIRECTION, "   ")
        assert responses.call is None

    def test_model_cannot_mark_a_fact_as_confirmed(self) -> None:
        with pytest.raises(ValidationError):
            ExtractedFactDraft(
                key="role.family",
                value="Embedded",
                level="preference",
                evidence_status="confirmed",
                confidence="high",
                source_quote="Embedded",
            )


class TestProfileReview:
    def make_fact(self, value: str = "Embedded") -> ProfileFact:
        return ProfileFact(
            key="role.family",
            value=value,
            level="preference",
            evidence_status="explicit",
            confidence="high",
            source=SourceExcerpt(section=ProfileSection.DIRECTION, text=value),
        )

    def test_confirm_appends_audit_event(self) -> None:
        fact = self.make_fact()
        profile = CandidateProfile(facts=[fact])

        apply_review(profile, fact.id, ReviewAction.CONFIRM)

        assert fact.evidence_status == EvidenceStatus.CONFIRMED
        assert fact.needs_confirmation is False
        assert profile.review_events[0].action == ReviewAction.CONFIRM

    def test_edit_is_authoritative_and_protected_from_model_refresh(self) -> None:
        fact = self.make_fact()
        profile = CandidateProfile(facts=[fact])
        apply_review(
            profile,
            fact.id,
            ReviewAction.EDIT_VALUE,
            new_value="Embedded engineering with AI tools",
        )
        proposal = self.make_fact("Embedded engineering with AI tools")

        result = merge_extracted_facts(profile, [proposal])

        assert fact.value == "Embedded engineering with AI tools"
        assert result.protected_fact_ids == [fact.id]
        assert len(profile.facts) == 1

    def test_change_level_confirms_user_intent(self) -> None:
        fact = self.make_fact()
        profile = CandidateProfile(facts=[fact])

        apply_review(
            profile,
            fact.id,
            ReviewAction.CHANGE_LEVEL,
            new_level=RequirementLevel.MUST_HAVE,
        )

        assert fact.level == RequirementLevel.MUST_HAVE
        assert fact.evidence_status == EvidenceStatus.CONFIRMED

    def test_rejected_fact_is_not_pending(self) -> None:
        fact = self.make_fact()
        profile = CandidateProfile(facts=[fact])

        apply_review(profile, fact.id, ReviewAction.REJECT)

        assert fact.evidence_status == EvidenceStatus.REJECTED
        assert profile.pending_facts == []

    def test_profile_round_trips_through_local_json(self) -> None:
        profile = CandidateProfile(facts=[self.make_fact()])
        with TemporaryDirectory() as directory:
            path = save_profile(profile, Path(directory))
            restored = CandidateProfile.model_validate_json(path.read_text(encoding="utf-8"))

        assert restored.id == profile.id
        assert restored.facts[0].value == "Embedded"

    def test_bulk_confirmation_accepts_only_safe_levels(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        preference = self.make_fact("Embedded")
        open_fact = self.make_fact("Test automation")
        open_fact.level = RequirementLevel.OPEN
        exclusion = self.make_fact("Sales-only work")
        exclusion.level = RequirementLevel.EXCLUSION
        profile = CandidateProfile(facts=[preference, open_fact, exclusion])

        stub_terminal(monkeypatch, ["a", "y", "c"])
        review_profile(profile)

        assert preference.evidence_status == EvidenceStatus.CONFIRMED
        assert open_fact.evidence_status == EvidenceStatus.CONFIRMED
        assert exclusion.evidence_status == EvidenceStatus.CONFIRMED
        assert len(profile.review_events) == 3

    def test_edit_requires_category_reconfirmation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fact = self.make_fact("Chronic overtime is unacceptable")
        fact.level = RequirementLevel.EXCLUSION
        profile = CandidateProfile(facts=[fact])

        stub_terminal(monkeypatch, ["e", "Exciting work is preferred", "n", "2"])
        review_profile(profile)

        assert fact.value == "Exciting work is preferred"
        assert fact.level == RequirementLevel.PREFERENCE
        assert fact.evidence_status == EvidenceStatus.CONFIRMED

    def test_completed_profile_editor_can_repair_a_fact(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fact = self.make_fact("Chronic overtime is unacceptable")
        fact.level = RequirementLevel.EXCLUSION
        fact.evidence_status = EvidenceStatus.CONFIRMED
        profile = CandidateProfile(facts=[fact])

        stub_terminal(
            monkeypatch,
            [
                "/find overtime",
                "e",
                "Exciting work is preferred",
                "n",
                "2",
                "q",
            ],
        )
        edit_confirmed_profile(profile)

        assert fact.value == "Exciting work is preferred"
        assert fact.level == RequirementLevel.PREFERENCE


class TestRuntime:
    def test_virtual_environment_detection_uses_python_prefix(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        monkeypatch.setattr("betteroption.runtime.sys.prefix", "C:\\project\\.venv")
        monkeypatch.setattr("betteroption.runtime.sys.base_prefix", "C:\\Python312")
        assert is_virtual_environment() is True


class TestProfileSession:
    def make_extraction(self, *, follow_up: str | None = None) -> SectionExtraction:
        return SectionExtraction(
            summary="Embedded engineering is preferred.",
            facts=[
                ExtractedFactDraft(
                    key="role.family",
                    value="Embedded engineering",
                    level="preference",
                    evidence_status="explicit",
                    confidence="high",
                    source_quote="embedded engineering",
                )
            ],
            follow_up_question=follow_up,
        )

    def test_new_session_has_nine_unique_core_sections(self) -> None:
        session = new_session()

        assert len(session.sections) == 9
        assert len({item.section for item in session.sections}) == 9
        assert next_pending_section(session) == ProfileSection.DIRECTION
        assert session.state == SessionState.ACTIVE
        assert set(SECTION_INSTRUCTIONS) == {
            definition.section for definition in CORE_SECTION_DEFINITIONS
        }

    def test_session_rejects_missing_or_reordered_core_sections(self) -> None:
        session = new_session()
        payload = session.model_dump()
        payload["sections"] = list(reversed(payload["sections"]))

        with pytest.raises(ValidationError):
            type(session).model_validate(payload)

    def test_skipping_advances_and_can_be_reopened(self) -> None:
        session = new_session()
        mark_section_skipped(session, ProfileSection.DIRECTION)

        assert next_pending_section(session) == ProfileSection.LOCATION_MOBILITY
        for progress in session.sections[1:]:
            mark_section_skipped(session, progress.section)
        assert session.state == SessionState.READY_WITH_SKIPS

        reopened = reopen_skipped_sections(session)

        assert reopened == 9
        assert session.state == SessionState.ACTIVE

    def test_extraction_is_checkpointed_as_review_pending(self) -> None:
        session = new_session()
        question = "Which role is the priority?"

        result = record_section_extraction(
            session,
            ProfileSection.DIRECTION,
            "I prefer embedded engineering.",
            self.make_extraction(follow_up=question),
            unresolved_follow_up=True,
        )

        progress = progress_for(session, ProfileSection.DIRECTION)
        assert progress.status == SectionStatus.REVIEW_PENDING
        assert next_review_section(session) == ProfileSection.DIRECTION
        assert progress.proposed_fact_ids == result.added_fact_ids
        assert question in session.profile.unresolved_questions
        assert (
            session.profile.raw_sections[ProfileSection.DIRECTION]
            == "I prefer embedded engineering."
        )

    def test_completed_review_advances_to_next_section(self) -> None:
        session = new_session()
        record_section_extraction(
            session,
            ProfileSection.DIRECTION,
            "I prefer embedded engineering.",
            self.make_extraction(),
        )

        complete_section_review(session, ProfileSection.DIRECTION)

        assert progress_for(session, ProfileSection.DIRECTION).status == SectionStatus.COMPLETED
        assert next_review_section(session) is None
        assert next_pending_section(session) == ProfileSection.LOCATION_MOBILITY
        assert session.completed_count == 1

    def test_all_completed_sections_finish_the_session(self) -> None:
        session = new_session()
        for progress in session.sections:
            progress.status = SectionStatus.REVIEW_PENDING
            complete_section_review(session, progress.section)

        assert session.state == SessionState.COMPLETED
        assert session.completed_at is not None

    def test_session_round_trips_and_latest_checkpoint_is_resolvable(self) -> None:
        session = new_session()
        mark_section_skipped(session, ProfileSection.DIRECTION)
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            path = save_session(session, directory_path)
            restored = load_session(path)
            latest = latest_session_path(directory_path)

        assert restored.id == session.id
        assert progress_for(restored, ProfileSection.DIRECTION).status == SectionStatus.SKIPPED
        assert latest == path

    def test_runner_resumes_pending_review_before_next_extraction(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = new_session()
        record_section_extraction(
            session,
            ProfileSection.DIRECTION,
            "I prefer embedded engineering.",
            self.make_extraction(),
        )
        fake_extractor = SimpleNamespace(model="test-model")

        stub_terminal(monkeypatch, ["c", "/quit"])
        with TemporaryDirectory() as directory, chdir(directory):
            result = run_session(session, fake_extractor)

        assert result == 0
        assert session.completed_count == 1
        assert session.profile.facts[0].evidence_status == EvidenceStatus.CONFIRMED
        assert next_pending_section(session) == ProfileSection.LOCATION_MOBILITY
