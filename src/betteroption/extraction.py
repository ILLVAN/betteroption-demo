"""Provider-neutral profile extraction contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import Field

from .profile import (
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    StrictModel,
)


class DraftEvidenceStatus(StrEnum):
    """A model can propose evidence, but it can never confirm user intent."""

    EXPLICIT = "explicit"
    INFERRED = "inferred"


class ExtractedFactDraft(StrictModel):
    """An atomic model proposal whose activation is decided by its input workflow."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    value: str = Field(min_length=1, max_length=1_000)
    level: RequirementLevel
    evidence_status: DraftEvidenceStatus
    confidence: Confidence
    source_quote: str = Field(min_length=1, max_length=2_000)


class SectionExtraction(StrictModel):
    """Structured result for exactly one guided free-text section."""

    summary: str = Field(min_length=1, max_length=2_000)
    facts: list[ExtractedFactDraft]
    follow_up_question: str | None

    def to_profile_facts(self, section: ProfileSection) -> list[ProfileFact]:
        return [
            ProfileFact(
                key=draft.key,
                value=draft.value,
                level=draft.level,
                evidence_status=EvidenceStatus(draft.evidence_status),
                confidence=draft.confidence,
                source=SourceExcerpt(section=section, text=draft.source_quote),
            )
            for draft in self.facts
        ]


class ExtractionProvider(Protocol):
    """Boundary implemented by OpenAI and future model providers."""

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction:
        """Extract reviewable facts from one user-authored profile section."""
