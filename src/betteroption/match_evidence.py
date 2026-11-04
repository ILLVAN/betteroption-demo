"""Validated semantic relations between Compass criteria and public job facts.

The language model is deliberately limited to an evidence-relation task.  It
does not receive account or persona metadata and it never decides a score or a
result disposition.  Matching remains the authoritative deterministic layer.
"""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
import json
from typing import Protocol
from uuid import UUID

from pydantic import Field, model_validator

from .job_context import ContextConfidence
from .jobs import JobFact, JobPosting
from .profile import ProfileFact, StrictModel


class SemanticFitOutcome(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    SUPPORTING = "supporting"
    UNKNOWN = "unknown"


def job_fact_fingerprint(fact: JobFact) -> str:
    """Bind an assessment to the exact evidence value that was evaluated."""

    payload = json.dumps(
        {
            "id": str(fact.id),
            "key": fact.key,
            "value": fact.value,
            "kind": fact.kind.value,
            "evidence_quote": fact.evidence_quote,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class SemanticMatchAssessment(StrictModel):
    """One server-validated, reusable relation for one job and criterion."""

    job_id: UUID
    profile_fact_id: UUID
    outcome: SemanticFitOutcome
    confidence: ContextConfidence
    evidence_job_fact_ids: list[UUID] = Field(default_factory=list, max_length=8)
    evidence_fact_fingerprints: dict[UUID, str] = Field(default_factory=dict)
    explanation: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def decisive_relation_has_bound_evidence(self) -> SemanticMatchAssessment:
        if self.outcome != SemanticFitOutcome.UNKNOWN and not self.evidence_job_fact_ids:
            raise ValueError("a decisive semantic relation requires job-fact evidence")
        if set(self.evidence_fact_fingerprints) != set(self.evidence_job_fact_ids):
            raise ValueError("semantic evidence fingerprints must match the referenced facts")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in self.evidence_fact_fingerprints.values()
        ):
            raise ValueError("semantic evidence fingerprint is invalid")
        return self


class MatchEvidenceResolverPort(Protocol):
    model: str

    def assess(
        self,
        *,
        profile_facts_by_job_id: dict[UUID, list[ProfileFact]],
        jobs: list[JobPosting],
    ) -> dict[UUID, list[SemanticMatchAssessment]]: ...


def evidence_is_current(
    assessment: SemanticMatchAssessment,
    job_facts: list[JobFact],
) -> bool:
    """Reject a stored relation when a user correction changed its evidence."""

    facts_by_id = {fact.id: fact for fact in job_facts}
    return all(
        (fact := facts_by_id.get(fact_id)) is not None
        and assessment.evidence_fact_fingerprints.get(fact_id) == job_fact_fingerprint(fact)
        for fact_id in assessment.evidence_job_fact_ids
    )
