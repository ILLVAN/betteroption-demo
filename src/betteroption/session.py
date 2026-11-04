"""Resumable guided profile-session domain model and persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .extraction import SectionExtraction
from .profile import CandidateProfile, ProfileSection, StrictModel
from .profile_mobility import (
    canonicalize_mobility_fact,
    canonicalize_profile_mobility_facts,
    explicit_mobility_facts_from_text,
)
from .review import MergeResult, merge_extracted_facts


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SectionStatus(StrEnum):
    PENDING = "pending"
    REVIEW_PENDING = "review_pending"
    CLARIFICATION_PENDING = "clarification_pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class SessionState(StrEnum):
    ACTIVE = "active"
    READY_WITH_SKIPS = "ready_with_skips"
    COMPLETED = "completed"


class SectionDefinition(StrictModel):
    section: ProfileSection
    title: str
    question: str
    guidance: str
    example: str
    suggestions: list[str] = Field(default_factory=list, max_length=6)


CORE_SECTION_DEFINITIONS = (
    SectionDefinition(
        section=ProfileSection.DIRECTION,
        title="Professional direction",
        question="What kind of work are you looking for?",
        guidance="Describe roles, responsibilities, domains, and the direction in which you want to grow.",
        example=(
            "I want a junior embedded-software or test-automation role with hands-on Python or C++, "
            "not pure manual testing or people management."
        ),
        suggestions=[
            "Target role and seniority",
            "Hands-on tasks and technologies",
            "Industries or products that interest me",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.LOCATION_MOBILITY,
        title="Location and mobility",
        question="Where can and would you like to work?",
        guidance=(
            "Include your starting point, acceptable destinations, commute limits by train, car, bicycle, "
            "or foot, and whether relocation or a second residence is an option."
        ),
        example=(
            "From 04109 Leipzig, no more than 45 minutes by train, 35 minutes by car, or "
            "25 minutes by bicycle one way. Relocation is not an option."
        ),
        suggestions=[
            "Starting address or postal code",
            "Maximum one-way time per travel mode",
            "Relocation or second-residence flexibility",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.WORKING_MODEL,
        title="Working model",
        question="How should your working week be organized?",
        guidance=(
            "Describe remote and office days, weekly hours, schedule flexibility, shifts, overtime, and travel."
        ),
        example=(
            "Hybrid with no more than two office days per week. I prefer 32–35 hours, flexible start "
            "times, no night shifts, and no regular travel."
        ),
        suggestions=[
            "On-site, hybrid, or remote arrangement",
            "Weekly hours and office days",
            "Shifts, overtime, on-call duty, and travel",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.COMPENSATION_TIME,
        title="Compensation and time",
        question="What compensation and time conditions do you expect?",
        guidance=(
            "State hard minimums, targets, benefits, vacation, and any trade-off between salary and free time."
        ),
        example=(
            "My minimum is EUR 58,000 gross per year. I would trade some salary for a four-day week "
            "or 35 hours, 30 vacation days, and strong development opportunities."
        ),
        suggestions=[
            "Minimum and target annual salary",
            "Weekly hours and vacation",
            "Benefits or salary–time trade-offs",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.MUST_HAVES,
        title="Non-negotiable requirements",
        question="Which conditions are genuinely mandatory?",
        guidance="List only conditions that would normally make you reject a job if they were missing.",
        example=(
            "A direct employer contract, at least EUR 58,000, no more than two office days, and no "
            "weekly business travel."
        ),
        suggestions=[
            "Contract and salary minimum",
            "Required work arrangement",
            "Maximum travel or commute",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.PREFERENCES,
        title="Positive preferences",
        question="What would make a role especially attractive?",
        guidance=(
            "Describe negotiable preferences involving tasks, technology, industry, contract, learning, and impact."
        ),
        example=(
            "Product development, test automation, a collective agreement, transparent salary bands, "
            "and a learning budget would be attractive."
        ),
        suggestions=[
            "Preferred tasks and technology",
            "Product, industry, or company type",
            "Learning, contract, and team preferences",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.EXCLUSIONS,
        title="Exclusions",
        question="What do you explicitly want to avoid?",
        guidance=(
            "Name unwanted roles, responsibilities, industries, employment models, and working conditions."
        ),
        example=(
            "No staffing agency, defence or people-surveillance products, outbound sales, pure manual "
            "testing, permanent on-call rotation, or pure management role."
        ),
        suggestions=[
            "Excluded industries or product categories",
            "Unwanted roles and responsibilities",
            "Employment models or working conditions to avoid",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.EXPERIENCE,
        title="Experience and evidence",
        question="What skills, experience, and evidence do you bring?",
        guidance=(
            "Describe education, projects, tools, responsibilities, outcomes, languages, and transferable skills. "
            "You can also upload a CV privately from Compass and review the proposed evidence."
        ),
        example=(
            "I have three years of Python test automation, CI/CD and embedded-system testing, a BSc in "
            "engineering, fluent German (C2), and professional English (C1)."
        ),
        suggestions=[
            "Skills, tools, and years of experience",
            "Education, projects, and measurable outcomes",
            "Languages and proficiency levels",
        ],
    ),
    SectionDefinition(
        section=ProfileSection.ENVIRONMENT_CULTURE,
        title="Environment, culture, and trade-offs",
        question="In which environment do you do your best work?",
        guidance=(
            "Make abstract ideas concrete: collaboration, feedback, autonomy, management, pace, hierarchy, team "
            "size, stability, and what you would trade for an unusually strong role."
        ),
        example=(
            "I want direct feedback, approachable colleagues, technical autonomy, and a sustainable pace. "
            "A smaller salary is acceptable for a healthy product team, but chronic overtime is not."
        ),
        suggestions=[
            "Feedback, autonomy, and management style",
            "Team size, pace, and stability",
            "Culture trade-offs I would accept",
        ],
    ),
)


class SectionProgress(StrictModel):
    section: ProfileSection
    status: SectionStatus = SectionStatus.PENDING
    summary: str | None = None
    follow_up_question: str | None = None
    clarification_answer: str | None = None
    proposed_fact_ids: list[UUID] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)


class ProfileSession(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    profile: CandidateProfile = Field(default_factory=CandidateProfile)
    sections: list[SectionProgress]
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def contains_canonical_core_sections(self) -> ProfileSession:
        expected = [definition.section for definition in CORE_SECTION_DEFINITIONS]
        actual = [progress.section for progress in self.sections]
        if actual != expected:
            raise ValueError("session sections must contain the nine core sections in order")
        return self

    @property
    def state(self) -> SessionState:
        statuses = {progress.status for progress in self.sections}
        if statuses == {SectionStatus.COMPLETED}:
            return SessionState.COMPLETED
        if not statuses.intersection(
            {
                SectionStatus.PENDING,
                SectionStatus.REVIEW_PENDING,
                SectionStatus.CLARIFICATION_PENDING,
            }
        ):
            return SessionState.READY_WITH_SKIPS
        return SessionState.ACTIVE

    @property
    def completed_count(self) -> int:
        return sum(progress.status == SectionStatus.COMPLETED for progress in self.sections)


def new_session() -> ProfileSession:
    return ProfileSession(
        sections=[SectionProgress(section=item.section) for item in CORE_SECTION_DEFINITIONS]
    )


def definition_for(section: ProfileSection) -> SectionDefinition:
    for definition in CORE_SECTION_DEFINITIONS:
        if definition.section == section:
            return definition
    raise KeyError(f"no core definition for section: {section}")


def progress_for(session: ProfileSession, section: ProfileSection) -> SectionProgress:
    for progress in session.sections:
        if progress.section == section:
            return progress
    raise KeyError(f"section is not part of this session: {section}")


def next_pending_section(session: ProfileSession) -> ProfileSection | None:
    for progress in session.sections:
        if progress.status == SectionStatus.PENDING:
            return progress.section
    return None


def next_review_section(session: ProfileSession) -> ProfileSection | None:
    for progress in session.sections:
        if progress.status == SectionStatus.REVIEW_PENDING:
            return progress.section
    return None


def next_clarification_section(session: ProfileSession) -> ProfileSection | None:
    for progress in session.sections:
        if progress.status == SectionStatus.CLARIFICATION_PENDING:
            return progress.section
    return None


def mark_section_skipped(session: ProfileSession, section: ProfileSection) -> None:
    progress = progress_for(session, section)
    progress.status = SectionStatus.SKIPPED
    progress.updated_at = _now()
    session.updated_at = progress.updated_at


def leave_clarification_open(session: ProfileSession, section: ProfileSection) -> None:
    progress = progress_for(session, section)
    if progress.status != SectionStatus.CLARIFICATION_PENDING:
        raise ValueError(f"section is not awaiting clarification: {section}")
    progress.status = SectionStatus.COMPLETED
    progress.updated_at = _now()
    session.updated_at = progress.updated_at
    if session.state == SessionState.COMPLETED:
        session.completed_at = session.updated_at


def reopen_skipped_sections(session: ProfileSession) -> int:
    reopened = 0
    for progress in session.sections:
        if progress.status == SectionStatus.SKIPPED:
            progress.status = SectionStatus.PENDING
            progress.updated_at = _now()
            reopened += 1
    if reopened:
        session.updated_at = _now()
    return reopened


def record_section_extraction(
    session: ProfileSession,
    section: ProfileSection,
    raw_text: str,
    extraction: SectionExtraction,
    *,
    unresolved_follow_up: bool = False,
    explicit_fact_text: str | None = None,
) -> MergeResult:
    """Merge an extraction and checkpoint it before user review begins."""

    clean_text = raw_text.strip()
    if not clean_text:
        raise ValueError("raw_text must not be empty")

    canonicalize_profile_mobility_facts(session.profile)
    proposals = extraction.to_profile_facts(section)
    if section == ProfileSection.LOCATION_MOBILITY:
        for proposal in proposals:
            canonicalize_mobility_fact(proposal)
        represented_keys = {proposal.key for proposal in proposals}
        proposals.extend(
            fact
            for fact in explicit_mobility_facts_from_text(explicit_fact_text or clean_text)
            if fact.key not in represented_keys
        )
    result = merge_extracted_facts(session.profile, proposals)
    session.profile.raw_sections[section] = clean_text

    if unresolved_follow_up and extraction.follow_up_question:
        question = extraction.follow_up_question
        if question not in session.profile.unresolved_questions:
            session.profile.unresolved_questions.append(question)

    progress = progress_for(session, section)
    progress.status = SectionStatus.REVIEW_PENDING
    progress.summary = extraction.summary
    progress.follow_up_question = extraction.follow_up_question
    progress.proposed_fact_ids = [
        *result.added_fact_ids,
        *result.refreshed_pending_fact_ids,
    ]
    progress.updated_at = _now()
    session.updated_at = progress.updated_at
    return result


def complete_section_review(session: ProfileSession, section: ProfileSection) -> None:
    progress = progress_for(session, section)
    if progress.status != SectionStatus.REVIEW_PENDING:
        raise ValueError(f"section is not awaiting review: {section}")
    progress.status = (
        SectionStatus.CLARIFICATION_PENDING
        if progress.follow_up_question and progress.clarification_answer is None
        else SectionStatus.COMPLETED
    )
    progress.updated_at = _now()
    session.updated_at = progress.updated_at
    if session.state == SessionState.COMPLETED:
        session.completed_at = session.updated_at


def save_session(
    session: ProfileSession,
    directory: Path = Path("local-data") / "sessions",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"session-{session.id}.json"
    path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_session(path: Path) -> ProfileSession:
    return ProfileSession.model_validate_json(path.read_text(encoding="utf-8"))


def latest_session_path(directory: Path = Path("local-data") / "sessions") -> Path | None:
    paths = list(directory.glob("session-*.json")) if directory.exists() else []
    return max(paths, key=lambda item: item.stat().st_mtime) if paths else None
