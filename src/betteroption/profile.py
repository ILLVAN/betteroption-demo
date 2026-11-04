"""Domain model for WorkLifeBalance Profile Protocol v0.1."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Annotated, Literal, get_args
import unicodedata
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RequirementLevel(StrEnum):
    MUST_HAVE = "must_have"
    PREFERENCE = "preference"
    EXCLUSION = "exclusion"
    OPEN = "open"


class EvidenceStatus(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    EDIT_VALUE = "edit_value"
    CHANGE_LEVEL = "change_level"
    REJECT = "reject"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProfileSection(StrEnum):
    DIRECTION = "direction"
    LOCATION_MOBILITY = "location_mobility"
    WORKING_MODEL = "working_model"
    COMPENSATION_TIME = "compensation_time"
    MUST_HAVES = "must_haves"
    PREFERENCES = "preferences"
    EXCLUSIONS = "exclusions"
    EXPERIENCE = "experience"
    ENVIRONMENT_CULTURE = "environment_culture"
    REFERENCES = "references"
    TRADE_OFFS = "trade_offs"


class SourceExcerpt(StrictModel):
    section: ProfileSection
    text: Annotated[str, Field(min_length=1, max_length=2_000)]
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> SourceExcerpt:
        if self.start_offset is not None and self.end_offset is not None:
            if self.end_offset < self.start_offset:
                raise ValueError("end_offset must not precede start_offset")
        return self


class ProfileFact(StrictModel):
    """One atomic, inspectable claim extracted from user language."""

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: datetime | None = None
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]*$")]
    value: str | int | float | bool | list[str]
    level: RequirementLevel = RequirementLevel.OPEN
    evidence_status: EvidenceStatus
    confidence: Confidence
    source: SourceExcerpt
    user_note: str | None = Field(default=None, max_length=1_000)
    # Typed many-to-one provenance for suggestions learned from reference jobs.
    # The default keeps profiles written before v0.7.1c readable.
    source_reference_ids: list[UUID] = Field(default_factory=list)
    needs_confirmation: bool = True

    @model_validator(mode="after")
    def inferred_facts_require_confirmation(self) -> ProfileFact:
        if self.evidence_status == EvidenceStatus.INFERRED:
            object.__setattr__(self, "needs_confirmation", True)
            if self.confidence == Confidence.HIGH:
                raise ValueError("inferred facts cannot claim high confidence")
        if self.evidence_status in {EvidenceStatus.CONFIRMED, EvidenceStatus.REJECTED}:
            object.__setattr__(self, "needs_confirmation", False)
        return self


class FactReviewEvent(StrictModel):
    """Append-only audit entry for an authoritative user decision."""

    fact_id: UUID
    action: ReviewAction
    previous_value: str | int | float | bool | list[str]
    new_value: str | int | float | bool | list[str]
    previous_level: RequirementLevel
    new_level: RequirementLevel
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TravelMode(StrEnum):
    TRANSIT = "transit"
    CAR = "car"
    BICYCLE = "bicycle"
    WALK = "walk"


class TravelConstraint(StrictModel):
    mode: TravelMode
    maximum_minutes_one_way: int = Field(ge=1, le=360)
    level: RequirementLevel = RequirementLevel.MUST_HAVE
    peak_time_required: bool = True


class LocationPreference(StrictModel):
    origin_label: str = Field(min_length=1, max_length=200)
    origin_precision: Literal["city", "postal_code", "address"] = "city"
    acceptable_destinations: list[str] = Field(default_factory=list)
    travel_constraints: list[TravelConstraint] = Field(default_factory=list)
    relocation: RequirementLevel = RequirementLevel.OPEN
    second_residence_allowed: bool | None = None


class WorkModel(StrictModel):
    maximum_office_days_per_week: int | None = Field(default=None, ge=0, le=7)
    minimum_remote_days_per_week: int | None = Field(default=None, ge=0, le=7)
    target_weekly_hours: float | None = Field(default=None, ge=1, le=80)
    maximum_weekly_hours: float | None = Field(default=None, ge=1, le=100)
    travel_frequency: RequirementLevel = RequirementLevel.OPEN

    @model_validator(mode="after")
    def hours_are_consistent(self) -> WorkModel:
        if (
            self.target_weekly_hours is not None
            and self.maximum_weekly_hours is not None
            and self.target_weekly_hours > self.maximum_weekly_hours
        ):
            raise ValueError("target_weekly_hours cannot exceed maximum_weekly_hours")
        return self


COMPENSATION_RANGE_MIN_EUR = 0
COMPENSATION_RANGE_MAX_EUR = 300_000

CompensationCurrency = Literal[
    "EUR",
    "GBP",
    "CHF",
    "NOK",
    "SEK",
    "DKK",
    "ISK",
    "PLN",
    "CZK",
    "HUF",
    "RON",
    "BGN",
    "ALL",
    "BAM",
    "MKD",
    "MDL",
    "RSD",
    "UAH",
    "BYN",
    "RUB",
    "GEL",
    "TRY",
    "AMD",
    "AZN",
    "USD",
    "CAD",
    "AUD",
    "NZD",
    "JPY",
    "CNY",
    "HKD",
    "SGD",
    "INR",
    "KRW",
    "AED",
    "ILS",
    "BRL",
    "MXN",
    "ZAR",
]
SUPPORTED_COMPENSATION_CURRENCIES: tuple[str, ...] = get_args(CompensationCurrency)


class Compensation(StrictModel):
    """Structured annual-gross orientation used by the Compass range editor.

    ``None`` remains the storage representation for an unconstrained edge so
    profiles saved before the range editor continue to validate unchanged. The
    UI projection maps an open minimum to 0 in the selected currency. An absent
    target remains absent: the visual ceiling is not a preference unless the
    candidate enters it deliberately.
    Values above the current UI ceiling remain readable for legacy profiles.
    """

    # EUR is deliberately the default so every pre-currency-selector profile
    # keeps exactly its previous meaning when loaded.
    currency: CompensationCurrency = "EUR"
    minimum_gross_annual: int | None = Field(default=None, ge=0)
    target_gross_annual: int | None = Field(default=None, ge=0)
    minimum_level: RequirementLevel = RequirementLevel.OPEN

    @property
    def range_minimum_gross_annual(self) -> int:
        value = self.minimum_gross_annual
        if value is None:
            return COMPENSATION_RANGE_MIN_EUR
        return min(value, COMPENSATION_RANGE_MAX_EUR)

    @property
    def range_target_gross_annual(self) -> int | None:
        value = self.target_gross_annual
        if value is None:
            return None
        return min(value, COMPENSATION_RANGE_MAX_EUR)

    @property
    def has_annual_gross_constraint(self) -> bool:
        return self.minimum_gross_annual is not None or self.target_gross_annual is not None

    @model_validator(mode="after")
    def salary_is_consistent(self) -> Compensation:
        if (
            self.minimum_gross_annual is not None
            and self.target_gross_annual is not None
            and self.target_gross_annual < self.minimum_gross_annual
        ):
            raise ValueError("target salary cannot be below minimum salary")
        return self


def set_compensation_range(
    profile: CandidateProfile,
    minimum_gross_annual: int,
    target_gross_annual: int | None,
    currency: CompensationCurrency | None = None,
) -> None:
    """Store a currency-qualified range while keeping open bounds semantically empty."""

    if isinstance(minimum_gross_annual, bool) or isinstance(target_gross_annual, bool):
        raise ValueError("annual salary values must be whole numbers")
    selected_currency = currency or profile.compensation.currency
    if selected_currency not in SUPPORTED_COMPENSATION_CURRENCIES:
        raise ValueError("select a supported ISO salary currency")
    if not COMPENSATION_RANGE_MIN_EUR <= minimum_gross_annual <= COMPENSATION_RANGE_MAX_EUR:
        raise ValueError(
            f"annual salary minimum must be between {selected_currency} 0 and "
            f"{selected_currency} 300,000"
        )
    if target_gross_annual is not None and not (
        minimum_gross_annual <= target_gross_annual <= COMPENSATION_RANGE_MAX_EUR
    ):
        raise ValueError(
            "annual salary target must be empty or between the minimum and "
            f"{selected_currency} 300,000"
        )
    profile.compensation.currency = selected_currency
    profile.compensation.minimum_gross_annual = (
        minimum_gross_annual if minimum_gross_annual > COMPENSATION_RANGE_MIN_EUR else None
    )
    profile.compensation.target_gross_annual = target_gross_annual
    profile.compensation.minimum_level = (
        RequirementLevel.MUST_HAVE
        if profile.compensation.minimum_gross_annual is not None
        else RequirementLevel.OPEN
    )
    profile.updated_at = datetime.now(timezone.utc)


class ReferenceJob(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    url: AnyHttpUrl
    input_method: Literal["verified_url", "manual_text"] = "verified_url"
    resolved_url: AnyHttpUrl | None = None
    url_http_status: int | None = Field(default=None, ge=100, le=599)
    url_verified_at: datetime | None = None
    positives: list[str] = Field(default_factory=list)
    negatives: list[str] = Field(default_factory=list)
    learning_enabled: bool = False
    learning_scope: list[Literal["role", "skills", "culture", "location", "work_model", "pay"]] = (
        Field(default_factory=list)
    )

    @model_validator(mode="after")
    def reference_is_safe_to_learn_from(self) -> ReferenceJob:
        if self.learning_scope and not self.learning_enabled:
            raise ValueError("learning_scope requires learning_enabled")
        verification_values = (
            self.resolved_url,
            self.url_http_status,
            self.url_verified_at,
        )
        if self.input_method == "manual_text":
            if any(value is not None for value in verification_values):
                raise ValueError("manual reference text cannot claim URL verification")
            return self
        if any(value is not None for value in verification_values):
            if not all(value is not None for value in verification_values):
                raise ValueError("reference URL verification metadata must be complete")
            if not 200 <= self.url_http_status < 300:
                raise ValueError("a verified reference URL requires a successful HTTP status")
        return self


class CandidateProfile(StrictModel):
    protocol_version: Literal["0.1"] = "0.1"
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_sections: dict[ProfileSection, str] = Field(default_factory=dict)
    facts: list[ProfileFact] = Field(default_factory=list)
    location: LocationPreference | None = None
    work_model: WorkModel = Field(default_factory=WorkModel)
    compensation: Compensation = Field(default_factory=Compensation)
    reference_jobs: list[ReferenceJob] = Field(default_factory=list)
    reference_learning_fact_ids: list[UUID] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    review_events: list[FactReviewEvent] = Field(default_factory=list)

    @property
    def confirmed_facts(self) -> list[ProfileFact]:
        """Return active facts without letting repeated extraction inflate the Compass.

        The audit log and original facts remain untouched. The newest equivalent
        statement wins in the active projection, so an existing private-alpha
        profile is cleaned up without a destructive data migration.
        """

        unique: dict[tuple[str, str], ProfileFact] = {}
        for fact in self.facts:
            if fact.evidence_status == EvidenceStatus.CONFIRMED:
                unique[profile_fact_signature(fact)] = fact
        active_ids = {fact.id for fact in unique.values()}
        return [fact for fact in self.facts if fact.id in active_ids]

    @property
    def pending_facts(self) -> list[ProfileFact]:
        return [fact for fact in self.facts if fact.needs_confirmation]

    @property
    def confirmed_candidate_evidence(self) -> list[ProfileFact]:
        """Confirmed capability evidence, never desired future-work preferences."""

        return [
            fact
            for fact in self.confirmed_facts
            if fact.source.section == ProfileSection.EXPERIENCE
            or fact.key.startswith(("candidate.", "education.", "experience."))
            or fact.key
            in {
                "skill.demonstrated",
                "skill.experience",
                "language.native",
                "language.proficiency",
                "language.spoken",
            }
        ]

    @property
    def confirmed_search_facts(self) -> list[ProfileFact]:
        evidence_ids = {fact.id for fact in self.confirmed_candidate_evidence}
        return [fact for fact in self.confirmed_facts if fact.id not in evidence_ids]


_EQUIVALENT_FACT_KEYS = {
    "skill.desired": "skill.name",
    "industry.desired": "industry.sector",
}

_SECTION_SCOPED_FACT_IDENTITY = {
    ProfileSection.DIRECTION,
    ProfileSection.MUST_HAVES,
    ProfileSection.PREFERENCES,
    ProfileSection.EXCLUSIONS,
    ProfileSection.EXPERIENCE,
    ProfileSection.ENVIRONMENT_CULTURE,
}


def profile_fact_signature(fact: ProfileFact) -> tuple[str, str]:
    """Build a conservative semantic identity for duplicate suppression."""

    key = _EQUIVALENT_FACT_KEYS.get(fact.key, fact.key)
    if fact.source.section in _SECTION_SCOPED_FACT_IDENTITY:
        # The same user intent can be classified under adjacent ontology keys by
        # different extractions. Within these prose-led sections, identical
        # normalized wording is one active statement; the newest decision wins.
        key = f"section:{fact.source.section.value}"
    values = fact.value if isinstance(fact.value, list) else [fact.value]
    normalized_values = sorted(_normalize_fact_value(value) for value in values)
    return key, " | ".join(normalized_values)


def _normalize_fact_value(value: object) -> str:
    material = unicodedata.normalize("NFKD", str(value).casefold())
    material = "".join(character for character in material if not unicodedata.combining(character))
    tokens = re.findall(r"[a-z0-9+#]+", material)
    return " ".join(token for token in tokens if token not in {"and", "und", "the"})
