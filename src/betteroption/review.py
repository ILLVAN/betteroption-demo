"""Authoritative user review operations for extracted profile facts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from pydantic import Field

from .profile import (
    CandidateProfile,
    EvidenceStatus,
    FactReviewEvent,
    ProfileFact,
    RequirementLevel,
    ReviewAction,
    StrictModel,
    profile_fact_signature,
)


class MergeResult(StrictModel):
    added_fact_ids: list[UUID] = Field(default_factory=list)
    refreshed_pending_fact_ids: list[UUID] = Field(default_factory=list)
    protected_fact_ids: list[UUID] = Field(default_factory=list)


def _find_fact(profile: CandidateProfile, fact_id: UUID) -> ProfileFact:
    for fact in profile.facts:
        if fact.id == fact_id:
            return fact
    raise KeyError(f"unknown fact id: {fact_id}")


def apply_review(
    profile: CandidateProfile,
    fact_id: UUID,
    action: ReviewAction,
    *,
    new_value: str | int | float | bool | list[str] | None = None,
    new_level: RequirementLevel | None = None,
) -> ProfileFact:
    """Apply one explicit user decision and append its audit event."""

    fact = _find_fact(profile, fact_id)
    reviewed_at = datetime.now(timezone.utc)
    previous_value = fact.value
    previous_level = fact.level

    if action == ReviewAction.EDIT_VALUE:
        if new_value is None or (isinstance(new_value, str) and not new_value.strip()):
            raise ValueError("EDIT_VALUE requires a non-empty new_value")
        fact.value = new_value
        fact.evidence_status = EvidenceStatus.CONFIRMED
        fact.user_note = "Edited by the user"
    elif action == ReviewAction.CHANGE_LEVEL:
        if new_level is None:
            raise ValueError("CHANGE_LEVEL requires new_level")
        fact.level = new_level
        fact.evidence_status = EvidenceStatus.CONFIRMED
        fact.user_note = "Category selected by the user"
    elif action == ReviewAction.CONFIRM:
        fact.evidence_status = EvidenceStatus.CONFIRMED
    elif action == ReviewAction.REJECT:
        fact.evidence_status = EvidenceStatus.REJECTED
        fact.user_note = "Rejected by the user"
    else:  # pragma: no cover - enum protects this branch
        raise ValueError(f"unsupported review action: {action}")

    event = FactReviewEvent(
        fact_id=fact.id,
        action=action,
        previous_value=previous_value,
        new_value=fact.value,
        previous_level=previous_level,
        new_level=fact.level,
        created_at=reviewed_at,
    )
    fact.reviewed_at = reviewed_at
    profile.review_events.append(event)
    profile.updated_at = reviewed_at
    return fact


def accept_user_input_facts(profile: CandidateProfile, fact_ids: list[UUID]) -> None:
    """Accept the interpretation of the user's own Compass answer immediately.

    This deliberately applies only to conversational Compass input. CV- and
    reference-derived proposals retain their explicit Review Tray because they
    are evidence about the user rather than a preference the user just stated.
    Existing confirmed or rejected decisions remain protected by the merge.
    """

    for fact_id in dict.fromkeys(fact_ids):
        fact = _find_fact(profile, fact_id)
        if fact.evidence_status in {EvidenceStatus.CONFIRMED, EvidenceStatus.REJECTED}:
            continue
        if fact.evidence_status == EvidenceStatus.INFERRED and fact.level in {
            RequirementLevel.MUST_HAVE,
            RequirementLevel.EXCLUSION,
        }:
            # Immediate activation is an active choice, but an interpretation
            # the model had to infer must never become an unseen hard boundary.
            apply_review(
                profile,
                fact_id,
                ReviewAction.CHANGE_LEVEL,
                new_level=RequirementLevel.OPEN,
            )
        else:
            apply_review(profile, fact_id, ReviewAction.CONFIRM)
        fact.user_note = "Accepted from the user's Compass answer; editable at any time"


def merge_extracted_facts(
    profile: CandidateProfile,
    proposals: list[ProfileFact],
) -> MergeResult:
    """Merge model proposals without overwriting a prior user decision."""

    result = MergeResult()
    for proposal in proposals:
        existing = next(
            (
                fact
                for fact in profile.facts
                if profile_fact_signature(fact) == profile_fact_signature(proposal)
            ),
            None,
        )
        if existing is None:
            profile.facts.append(proposal)
            result.added_fact_ids.append(proposal.id)
            continue

        if existing.evidence_status in {EvidenceStatus.CONFIRMED, EvidenceStatus.REJECTED}:
            result.protected_fact_ids.append(existing.id)
            continue

        index = profile.facts.index(existing)
        proposal.id = existing.id
        profile.facts[index] = proposal
        result.refreshed_pending_fact_ids.append(existing.id)

    profile.updated_at = datetime.now(timezone.utc)
    return result


def save_profile(profile: CandidateProfile, directory: Path = Path("local-data")) -> Path:
    """Persist private alpha data locally in a git-ignored directory."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"profile-{profile.id}.json"
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path
