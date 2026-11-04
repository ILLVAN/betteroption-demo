"""Deterministic, evidence-backed matching for confirmed profile facts."""

from __future__ import annotations

from hashlib import sha256
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, Field, model_validator

from .candidate_languages import (
    SPOKEN_LANGUAGES,
    mentioned_programming_languages,
    spoken_language_aliases,
)
from .company_intelligence import CompanyIntelligence
from .job_context import ContextConfidence, EmployerAssessment, EmployerKind, JobContext
from .job_overrides import (
    JobEvidenceOverride,
    JobEvidenceOverrideKind,
    ReasonOverrideValue,
    SkillOverrideValue,
)
from .jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from .mobility import CommuteAssessment, CommuteStatus
from .match_evidence import (
    MatchEvidenceResolverPort,
    SemanticFitOutcome,
    SemanticMatchAssessment,
    evidence_is_current,
)
from .presentation import job_is_remote_only
from .profile import (
    SUPPORTED_COMPENSATION_CURRENCIES,
    CandidateProfile,
    ProfileFact,
    RequirementLevel,
    StrictModel,
    TravelMode,
)
from .profile_mobility import mobility_limit_from_fact, mobility_mode_label
from .posting_date import (
    PostingDateAssessment,
    classify_posting_date,
    posting_date_score_adjustment,
)
from .salary import (
    SalaryConfidence,
    SalaryEstimate,
    SalaryEstimateKind,
    SalaryEvidence,
    SalaryGuess,
    estimate_salary,
)


class MatchDisposition(StrEnum):
    TOP = "top"
    STRETCH = "stretch"
    BLOCKED = "blocked"


class MatchOutcome(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    SUPPORTING = "supporting"


class SeniorityLevel(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid-level"
    SENIOR = "senior"
    LEAD = "lead"
    MANAGER = "manager"


class SeniorityAssessment(StrictModel):
    level: SeniorityLevel | None = None
    confidence: ContextConfidence = ContextConfidence.LOW
    explanation: str
    evidence_quotes: list[str] = Field(default_factory=list)


class EmployerReputationImpact(StrictModel):
    """Emotional compatibility effect of a private employer rating.

    Ratings can materially lower compatibility, but they are not Compass
    evidence and can never create a boundary violation.
    """

    stars: int = Field(ge=0, le=5)
    score_adjustment: int = Field(ge=-100, le=8)
    hard_blocker: bool = False


class JobRatingImpact(StrictModel):
    """Emotional compatibility effect of a private rating for this exact job."""

    stars: int = Field(ge=0, le=5)
    score_adjustment: int = Field(ge=-100, le=8)
    hard_blocker: bool = False


class ScoreInfluenceSection(StrictModel):
    """Traceable contribution to the deterministic score.

    ``positive_capacity_share_percent`` is derived from this algorithm's
    configured maximum positive adjustments. It is not presented as a learned
    statistical weight or as a guarantee that the section contributes points.
    """

    key: str
    label: str
    positive_capacity_points: int = Field(ge=0)
    positive_capacity_share_percent: float = Field(ge=0, le=100)
    applied_points: int
    mechanics: str
    can_block: bool = False


class ScoreMechanics(StrictModel):
    base_points: int
    pre_confidence_points: int
    evidence_confidence_multiplier: float = Field(ge=0.72, le=1.0)
    evidence_confidence_adjustment: int
    sections: list[ScoreInfluenceSection]
    final_points: int = Field(ge=0, le=100)


class ContextEvidenceCorrection(StrictModel):
    """A private corrected value layered over immutable machine evidence."""

    target_key: str
    target_label: str
    user_value: str


class MatchReason(StrictModel):
    profile_fact_id: UUID
    profile_key: str
    profile_value: str
    outcome: MatchOutcome
    explanation: str
    evidence_quotes: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    reasoning_confidence: ContextConfidence | None = None
    automatic_outcome: MatchOutcome | None = None
    user_overridden: bool = False
    user_override_note: str | None = None
    ai_assisted: bool = False


class MatchResult(StrictModel):
    job_id: UUID
    job_url: AnyHttpUrl | None = None
    source_is_manual: bool = False
    url_status: JobUrlStatus | None = None
    url_http_status: int | None = Field(default=None, ge=100, le=599)
    url_verified_at: datetime | None = None
    score: int = Field(ge=0, le=100)
    hard_evidence_coverage: int = Field(ge=0, le=100)
    disposition: MatchDisposition
    hard_violations: int = Field(ge=0)
    reasons: list[MatchReason] = Field(default_factory=list)
    semantic_assessments: list[SemanticMatchAssessment] = Field(default_factory=list)
    commutes: list[CommuteAssessment] = Field(default_factory=list)
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    user_overridden_matched_skills: list[str] = Field(default_factory=list)
    user_overridden_missing_skills: list[str] = Field(default_factory=list)
    employer_assessment: EmployerAssessment | None = None
    derived_work_mode_facts: list[JobFact] = Field(default_factory=list)
    effective_work_mode_facts: list[JobFact] = Field(default_factory=list)
    automatic_salary_estimate: SalaryEstimate | None = None
    salary_estimate: SalaryEstimate | None = None
    company_intelligence: CompanyIntelligence | None = None
    posting_date: PostingDateAssessment | None = None
    employer_reputation: EmployerReputationImpact | None = None
    job_rating: JobRatingImpact | None = None
    score_mechanics: ScoreMechanics | None = None
    effective_employer_assessment: EmployerAssessment | None = None
    effective_company_intelligence: CompanyIntelligence | None = None
    context_evidence_corrections: list[ContextEvidenceCorrection] = Field(default_factory=list)
    remote_only_mobility: bool = False
    remote_only_excluded: bool = False
    remote_mobility_points: int = Field(default=0, ge=0)
    # Semantic lineage makes a cheap local rescore distinguishable from a
    # provider-backed evidence refresh.  These fields are optional so saved
    # pre-Q results remain readable and receive one conservative full-refresh
    # opportunity.
    profile_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_evidence_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    user_evidence_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    # Ratings are intentionally separate from private evidence lineage. A
    # quickscore can update this projection locally without claiming that
    # Compass, source, or corrected evidence received a full refresh.
    rating_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def verified_job_link_is_complete(self) -> MatchResult:
        # A manually pasted advertisement may retain the user's optional
        # reference URL, but that URL was deliberately never fetched.  Keep it
        # as attribution without inventing reachability metadata or rejecting
        # the otherwise matchable local text.
        if self.source_is_manual:
            if any(
                value is not None
                for value in (
                    self.url_status,
                    self.url_http_status,
                    self.url_verified_at,
                )
            ):
                raise ValueError("manual match cannot claim URL verification")
            return self
        link_values = (
            self.job_url,
            self.url_status,
            self.url_http_status,
            self.url_verified_at,
        )
        if any(value is not None for value in link_values):
            if not all(value is not None for value in link_values):
                raise ValueError("match URL verification metadata must be complete")
            if self.url_status != JobUrlStatus.VERIFIED_REACHABLE:
                raise ValueError("match URL must be verified reachable")
            if not 200 <= self.url_http_status < 300:
                raise ValueError("match URL requires a successful HTTP status")
        return self


_FINGERPRINT_VOLATILE_FIELDS = frozenset(
    {
        "created_at",
        "updated_at",
        "reviewed_at",
        "checked_at",
        "observed_at",
        "url_checked_at",
    }
)


def _semantic_payload(value: object) -> object:
    """Return canonical JSON data without operational timestamps.

    Fingerprints answer whether scoring inputs changed, not whether a row was
    merely read, checked, or rewritten later.  UUIDs and attributable content
    remain in the payload, while timestamps that do not change meaning do not.
    """

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            str(key): _semantic_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _FINGERPRINT_VOLATILE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_payload(item) for item in value]
    return value


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        _semantic_payload(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def profile_evidence_fingerprint(profile: CandidateProfile) -> str:
    """Fingerprint the semantic Compass input used by deterministic matching."""

    return _fingerprint(profile)


def job_source_evidence_fingerprint(job: JobPosting) -> str:
    """Fingerprint one immutable source snapshot, excluding check timestamps."""

    return _fingerprint(job)


def user_evidence_fingerprint(
    overrides: list[JobEvidenceOverride] | None,
) -> str:
    """Fingerprint corrected private evidence, excluding emotional ratings."""

    semantic_overrides = []
    for override in overrides or []:
        payload = override.model_dump(
            mode="json",
            exclude={
                "id",
                "workspace_id",
                "job_record_id",
                "created_at",
                "updated_at",
            },
        )
        semantic_overrides.append(payload)
    semantic_overrides.sort(
        key=lambda item: (
            str(item.get("kind", "")),
            str(item.get("target_key", "")),
        )
    )
    return _fingerprint({"overrides": semantic_overrides})


def rating_input_fingerprint(
    *,
    employer_reputation_stars: int | None,
    job_rating_stars: int | None,
) -> str:
    """Fingerprint only the two current emotional compatibility inputs."""

    return _fingerprint(
        {
            "employer_reputation_stars": employer_reputation_stars,
            "job_rating_stars": job_rating_stars,
        }
    )


def legacy_user_evidence_fingerprint(
    overrides: list[JobEvidenceOverride] | None,
    *,
    employer_reputation_stars: int | None,
    job_rating_stars: int | None,
) -> str:
    """Reproduce the pre-split fingerprint for compatible saved-result reads."""

    semantic_overrides = []
    for override in overrides or []:
        payload = override.model_dump(
            mode="json",
            exclude={
                "id",
                "workspace_id",
                "job_record_id",
                "created_at",
                "updated_at",
            },
        )
        semantic_overrides.append(payload)
    semantic_overrides.sort(
        key=lambda item: (
            str(item.get("kind", "")),
            str(item.get("target_key", "")),
        )
    )
    return _fingerprint(
        {
            "overrides": semantic_overrides,
            "employer_reputation_stars": employer_reputation_stars,
            "job_rating_stars": job_rating_stars,
        }
    )


class MatchRun(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    profile_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    algorithm_version: str = "matching-v0.7.2i"
    results: list[MatchResult]


KEY_ALIASES = {
    "industry.desired": "industry.sector",
    "skill.desired": "skill.name",
    "skill.excluded": "skill.name",
    "compensation.minimum": "compensation.annual_gross",
    "salary.minimum_eur": "compensation.annual_gross",
    "work_model.hours_weekly": "work_model.weekly_hours",
}

PHRASE_ALIASES = {
    "embedded software engineering": "embedded software",
    "embedded engineering": "embedded software",
    "fpga dev": "fpga development",
    "ai prompt engineer": "prompt engineering",
    "ai prompt engineering": "prompt engineering",
    "temporary agency employment": "temporary agency",
    "employee leasing": "temporary agency",
    "arbeitnehmerüberlassung": "temporary agency",
    "technical product development": "product development",
    "software/product development": "product development",
    "c/c++": "c++",
}

PROFILE_CONTEXT_ONLY_KEYS = {
    "location.origin",
    "commute.origin",
    "mobility.origin",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "for",
    "in",
    "is",
    "of",
    "or",
    "the",
    "to",
    "with",
}

NUMBER_WORDS = {
    "zero": 0.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
}


def canonical_key(key: str) -> str:
    return KEY_ALIASES.get(key, key)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    for source, replacement in PHRASE_ALIASES.items():
        text = text.replace(source, replacement)
    return " ".join(re.findall(r"[a-z0-9+#]+", text))


def _tokens(value: object) -> set[str]:
    return {token for token in normalize_text(value).split() if token not in STOP_WORDS}


def semantic_similarity(left: object, right: object) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return 0.85
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _numbers(value: object) -> list[float]:
    text = str(value).casefold()
    numbers: list[float] = []
    for number in re.findall(r"\d+(?:[.,]\d+)?", text):
        parts = re.split(r"[.,]", number)
        if len(parts) == 2 and len(parts[1]) == 3:
            numbers.append(float("".join(parts)))
        else:
            numbers.append(float(number.replace(",", ".")))
    numbers.extend(
        numeric_value
        for word, numeric_value in NUMBER_WORDS.items()
        if re.search(rf"\b{word}\b", text)
    )
    return numbers


_SALARY_CURRENCY_CODE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(SUPPORTED_COMPENSATION_CURRENCIES)})\b",
    flags=re.IGNORECASE,
)
_WORD_LIKE_CURRENCY_CODES = frozenset({"ALL", "RUB", "TRY"})


def _explicit_salary_currency(value: object) -> str | None:
    """Return only an unambiguous currency marker from salary evidence."""

    material = str(value)
    for match in _SALARY_CURRENCY_CODE_PATTERN.finditer(material):
        token = match.group(0)
        normalized = token.upper()
        if normalized in _WORD_LIKE_CURRENCY_CODES and token != normalized:
            continue
        return normalized
    if "€" in material:
        return "EUR"
    if "£" in material:
        return "GBP"
    if "₹" in material:
        return "INR"
    if "₩" in material:
        return "KRW"
    if "₽" in material:
        return "RUB"
    if "₴" in material:
        return "UAH"
    if "₺" in material:
        return "TRY"
    if "₪" in material:
        return "ILS"
    # Dollar, yen/yuan and generic ``kr`` signs do not identify one currency.
    if any(marker in material for marker in ("$", "¥", "￥")):
        return "AMBIGUOUS"
    return None


def _salary_values_are_comparable(profile_value: object, job_value: object) -> bool:
    """Allow numeric pay comparisons only in a proven common currency.

    Currency-less historical Compass facts keep their original EUR meaning.
    Currency-less job facts remain comparable to those legacy EUR facts for
    backward compatibility; a non-EUR Compass amount always requires an
    explicit matching ISO code on the advertisement evidence.
    """

    profile_currency = _explicit_salary_currency(profile_value) or "EUR"
    job_currency = _explicit_salary_currency(job_value)
    if job_currency is None:
        return profile_currency == "EUR"
    return profile_currency == job_currency


def _comparable_job_facts(profile_fact: ProfileFact, job: JobPosting) -> list[JobFact]:
    key = canonical_key(profile_fact.key)
    if key == "work_model.office_days_max":
        return [fact for fact in job.facts if fact.key == "work_model.office_days"]
    return [fact for fact in job.facts if canonical_key(fact.key) == key]


def _strip_exclusion_language(value: object) -> str:
    text = normalize_text(value)
    prefixes = (
        "no ",
        "not ",
        "do not want ",
        "unacceptable ",
    )
    for prefix in prefixes:
        if text.startswith(prefix):
            return text.removeprefix(prefix)
    return text


def _evaluate_exclusion(
    profile_fact: ProfileFact,
    job_facts: list[JobFact],
) -> tuple[MatchOutcome, list[JobFact]]:
    target = _strip_exclusion_language(profile_fact.value)
    matches: list[JobFact] = []
    explicit_absence: list[JobFact] = []
    for fact in job_facts:
        job_value = normalize_text(fact.value)
        if canonical_key(profile_fact.key) == "work_model.shift_work":
            if job_value.startswith("no ") or "without shift" in job_value:
                explicit_absence.append(fact)
                continue
        if semantic_similarity(target, job_value) >= 0.5:
            matches.append(fact)
    if matches:
        return MatchOutcome.VIOLATED, matches
    if explicit_absence:
        return MatchOutcome.SATISFIED, explicit_absence
    return MatchOutcome.UNKNOWN, []


def _evaluate_must_have(
    profile_fact: ProfileFact,
    job_facts: list[JobFact],
) -> tuple[MatchOutcome, list[JobFact]]:
    if not job_facts:
        return MatchOutcome.UNKNOWN, []

    key = canonical_key(profile_fact.key)
    if key == "work_model.office_days_max":
        profile_numbers = _numbers(profile_fact.value)
        for fact in job_facts:
            job_numbers = _numbers(fact.value)
            if profile_numbers and job_numbers:
                return (
                    (MatchOutcome.SATISFIED, [fact])
                    if max(job_numbers) <= max(profile_numbers)
                    else (MatchOutcome.VIOLATED, [fact])
                )

    if key == "compensation.annual_gross":
        profile_numbers = _numbers(profile_fact.value)
        comparable_salary_facts = [
            fact
            for fact in job_facts
            if _salary_values_are_comparable(profile_fact.value, fact.value)
        ]
        advertised_numbers = [
            number for fact in comparable_salary_facts for number in _numbers(fact.value)
        ]
        if profile_numbers and advertised_numbers:
            target = max(profile_numbers)
            return (
                (MatchOutcome.SATISFIED, comparable_salary_facts)
                if max(advertised_numbers) >= target
                else (MatchOutcome.VIOLATED, comparable_salary_facts)
            )

    if key == "work_model.remote":
        for fact in job_facts:
            value = normalize_text(fact.value)
            if "remote" in value or "hybrid" in value:
                return MatchOutcome.SATISFIED, [fact]
            if "onsite" in value or "office only" in value:
                return MatchOutcome.VIOLATED, [fact]

    if key == "employment.arrangement":
        target = normalize_text(profile_fact.value)
        for fact in job_facts:
            value = normalize_text(fact.value)
            if semantic_similarity(target, value) >= 0.5:
                return MatchOutcome.SATISFIED, [fact]
            if "direct" in target and "temporary agency" in value:
                return MatchOutcome.VIOLATED, [fact]

    matches = [
        fact for fact in job_facts if semantic_similarity(profile_fact.value, fact.value) >= 0.5
    ]
    return (MatchOutcome.SATISFIED, matches) if matches else (MatchOutcome.UNKNOWN, [])


def _hard_reason(
    profile_fact: ProfileFact,
    job: JobPosting,
    employer: EmployerAssessment | None = None,
    company_intelligence: CompanyIntelligence | None = None,
) -> MatchReason:
    seniority_reason = _seniority_reason(profile_fact, job)
    if seniority_reason is not None:
        return seniority_reason
    employment_reason = _employment_reason(profile_fact, employer)
    if employment_reason is not None:
        return employment_reason
    company_reason = _company_exclusion_reason(profile_fact, company_intelligence)
    if company_reason is not None:
        return company_reason
    job_facts = _comparable_job_facts(profile_fact, job)
    if profile_fact.level == RequirementLevel.EXCLUSION:
        outcome, evidence = _evaluate_exclusion(profile_fact, job_facts)
        explanation = {
            MatchOutcome.VIOLATED: "The advertisement contains an excluded characteristic.",
            MatchOutcome.SATISFIED: "The advertisement explicitly rules out this excluded characteristic.",
            MatchOutcome.UNKNOWN: "The advertisement does not prove whether this exclusion applies.",
        }[outcome]
    else:
        outcome, evidence = _evaluate_must_have(profile_fact, job_facts)
        explanation = {
            MatchOutcome.SATISFIED: "The advertisement explicitly supports this must-have.",
            MatchOutcome.VIOLATED: "The advertisement conflicts with this must-have.",
            MatchOutcome.UNKNOWN: "The advertisement does not provide enough evidence for this must-have.",
        }[outcome]
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=explanation,
        evidence_quotes=[fact.evidence_quote for fact in evidence],
    )


def _company_exclusion_reason(
    profile_fact: ProfileFact,
    intelligence: CompanyIntelligence | None,
) -> MatchReason | None:
    """Resolve only proven sensitive business categories against explicit exclusions."""

    if profile_fact.level != RequirementLevel.EXCLUSION or intelligence is None:
        return None
    material = normalize_text(f"{profile_fact.key} {profile_fact.value}")
    requested_categories = _sensitive_exclusion_categories(material)
    if any(
        marker in material
        for marker in (
            "staffing",
            "temporary agency",
            "recruitment agency",
            "personaldienstleister",
            "zeitarbeit",
        )
    ):
        requested_categories.update({"staffing", "recruitment"})
    if "consulting" in material or "consultancy" in material:
        requested_categories.add("consulting")
    matched = requested_categories.intersection(intelligence.product.sensitive_categories)
    if not matched:
        if (
            requested_categories
            and intelligence.product.categories
            and intelligence.product.confidence.value in {"medium", "high"}
            and intelligence.product.evidence_urls
        ):
            return MatchReason(
                profile_fact_id=profile_fact.id,
                profile_key=profile_fact.key,
                profile_value=str(profile_fact.value),
                outcome=MatchOutcome.SUPPORTING,
                explanation=(
                    "Attributed public product evidence describes this employer as "
                    f"{intelligence.product.revenue_model}. It contains no indication of the "
                    f"excluded {', '.join(sorted(requested_categories))} category. This reduces "
                    "the concern but does not prove absence."
                ),
                evidence_quotes=intelligence.product.evidence_quotes,
                evidence_urls=intelligence.product.evidence_urls,
                reasoning_confidence=ContextConfidence(intelligence.product.confidence.value),
            )
        return None
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=MatchOutcome.VIOLATED,
        explanation=(
            "Public company-product evidence connects this employer to an excluded business category: "
            f"{', '.join(sorted(matched))}."
        ),
        evidence_quotes=intelligence.product.evidence_quotes,
        evidence_urls=intelligence.product.evidence_urls,
        reasoning_confidence=ContextConfidence(intelligence.product.confidence.value),
    )


def _sensitive_exclusion_categories(material: str) -> set[str]:
    """Classify explicit profile intent with the same narrow semantics as evidence."""

    categories: set[str] = set()
    if re.search(
        r"\b(?:military|armed forces|bundeswehr|wehrtechnik\w*|rustung\w*|ruestung\w*|"
        r"militar\w*)\b",
        material,
    ):
        categories.add("defence")
    else:
        defence = re.search(r"\bdefen[cs]e\b", material)
        defence_context = re.search(
            r"\b(?:weapons?|missiles?|army|naval|air force|soldiers?|radar|combat|"
            r"defen[cs]e (?:industry|sector|products?|systems?|customers?|contractors?|"
            r"technology|services?))\b",
            material,
        )
        cyber_context = re.search(
            r"\b(?:cyber|network|malware|information|cloud)\s+(?:security|defen[cs]e)\b|"
            r"\b(?:cybersecurity|network security|cloud security)\b",
            material,
        )
        if defence and defence_context and not cyber_context:
            categories.add("defence")
    if re.search(
        r"\b(?:video[- ]?surveillance\w*|human surveillance\w*|cctv|facial recognition|"
        r"biometric (?:monitoring|identification|recognition)|surveillance cameras?|"
        r"surveillance products?|(?:person|people|employee|workplace|police|intelligence)"
        r"[- ]surveillance\w*|videouberwach\w*|uberwachungskamera\w*|"
        r"personenuberwach\w*|mitarbeiteruberwach\w*|gesichtserkenn\w*|"
        r"biometrisch\w* uberwach\w*)\b",
        material,
    ):
        categories.add("surveillance")
    return categories


def _company_preference_reason(
    profile_fact: ProfileFact,
    intelligence: CompanyIntelligence | None,
) -> MatchReason | None:
    """Support open-ended preferences only when attributed company text overlaps."""

    if intelligence is None or not intelligence.product.evidence_urls:
        return None
    material = " ".join(
        [
            intelligence.product.summary,
            intelligence.product.revenue_model,
            *intelligence.product.categories,
        ]
    )
    if semantic_similarity(profile_fact.value, material) < 0.34:
        return None
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=MatchOutcome.SUPPORTING,
        explanation="Attributed public company-product evidence supports this preference.",
        evidence_quotes=intelligence.product.evidence_quotes,
        evidence_urls=intelligence.product.evidence_urls,
        reasoning_confidence=ContextConfidence(intelligence.product.confidence.value),
    )


_SENIORITY_TARGET_MARKERS: tuple[tuple[SeniorityLevel, tuple[str, ...]], ...] = (
    (
        SeniorityLevel.INTERN,
        ("intern", "internship", "working student", "werkstudent", "praktikum"),
    ),
    (
        SeniorityLevel.JUNIOR,
        (
            "junior",
            "entry level",
            "entry-level",
            "graduate",
            "trainee",
            "career starter",
            "berufseinsteiger",
            "absolvent",
        ),
    ),
    (SeniorityLevel.MID, ("mid level", "mid-level", "intermediate")),
    (SeniorityLevel.SENIOR, ("senior", "principal", "staff engineer", "architect")),
    (SeniorityLevel.LEAD, ("lead", "team lead", "tech lead")),
    (SeniorityLevel.MANAGER, ("manager", "head of", "director")),
)

_YEARS_EXPERIENCE_PATTERN = re.compile(
    r"\b(?:(?:at\s+least|minimum|min\.?|mindestens)\s+)?"
    r"(?P<years>\d{1,2})(?:\s*[-–]\s*\d{1,2})?\+?\s*"
    r"(?:years?|yrs?|jahre?n?)\b",
    re.I,
)

_EARLY_CAREER_PATTERN = re.compile(
    r"\b(?:intern(?:ship)?|working student|werkstudent|praktikum|"
    r"graduate|entry[- ]level|career starter|career entry|first job|"
    r"first professional experience|no experience required|trainee|junior|"
    r"berufseinsteiger\w*|absolvent\w*|karriereeinstieg|erste berufserfahrung)\b",
    re.I,
)

_LEADERSHIP_PATTERN = re.compile(
    r"\b(?:lead|manage)\s+(?:a|the|our)?\s*team\b|"
    r"\b(?:people|line) management\b|\bdirect reports?\b|"
    r"\b(?:team leadership|disciplinary responsibility|führungserfahrung|"
    r"disziplinarische verantwortung|personalverantwortung)\b",
    re.I,
)


def _profile_seniority_targets(profile_fact: ProfileFact) -> set[SeniorityLevel]:
    key = canonical_key(profile_fact.key)
    material = normalize_text(profile_fact.value)
    key_is_seniority = any(
        marker in key
        for marker in (
            "seniority",
            "career.level",
            "career.stage",
            "experience.level",
            "role.level",
        )
    )
    targets = {
        level
        for level, markers in _SENIORITY_TARGET_MARKERS
        if any(_contains_semantic_marker(material, marker) for marker in markers)
    }
    return targets if key_is_seniority or targets else set()


def _contains_semantic_marker(normalized_material: str, marker: str) -> bool:
    """Match a normalized word or phrase, never a substring of another word."""

    normalized_marker = normalize_text(marker)
    if not normalized_marker:
        return False
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_marker)}(?![a-z0-9])",
            normalized_material,
        )
    )


def _job_seniority(job: JobPosting) -> SeniorityAssessment:
    title = normalize_text(job.title)
    source = job.source_text

    title_order = (
        SeniorityLevel.MANAGER,
        SeniorityLevel.LEAD,
        SeniorityLevel.SENIOR,
        SeniorityLevel.INTERN,
        SeniorityLevel.JUNIOR,
        SeniorityLevel.MID,
    )
    for level in title_order:
        markers = dict(_SENIORITY_TARGET_MARKERS)[level]
        marker = next(
            (candidate for candidate in markers if _contains_semantic_marker(title, candidate)),
            None,
        )
        if marker:
            return SeniorityAssessment(
                level=level,
                confidence=ContextConfidence.HIGH,
                explanation=f"The role title explicitly signals {level.value} seniority.",
                evidence_quotes=[job.title],
            )

    early_match = _EARLY_CAREER_PATTERN.search(source)
    if early_match:
        return SeniorityAssessment(
            level=(
                SeniorityLevel.INTERN
                if any(
                    marker in normalize_text(early_match.group(0))
                    for marker in ("intern", "praktikum", "working student", "werkstudent")
                )
                else SeniorityLevel.JUNIOR
            ),
            confidence=ContextConfidence.HIGH,
            explanation="The advertisement contains an explicit early-career signal.",
            evidence_quotes=[_sentence_excerpt(source, early_match.start())],
        )

    years_matches = list(_YEARS_EXPERIENCE_PATTERN.finditer(source))
    if years_matches:
        minimum_years = max(int(match.group("years")) for match in years_matches)
        if minimum_years >= 5:
            level = SeniorityLevel.SENIOR
        elif minimum_years >= 3:
            level = SeniorityLevel.MID
        else:
            level = SeniorityLevel.JUNIOR
        strongest = max(years_matches, key=lambda match: int(match.group("years")))
        return SeniorityAssessment(
            level=level,
            confidence=ContextConfidence.MEDIUM,
            explanation=(
                f"The stated minimum experience supports a {level.value} classification; "
                "the employer's internal grade may still differ."
            ),
            evidence_quotes=[_sentence_excerpt(source, strongest.start())],
        )

    leadership_match = _LEADERSHIP_PATTERN.search(source)
    if leadership_match:
        return SeniorityAssessment(
            level=SeniorityLevel.LEAD,
            confidence=ContextConfidence.MEDIUM,
            explanation="The responsibilities include explicit team or people leadership.",
            evidence_quotes=[_sentence_excerpt(source, leadership_match.start())],
        )

    if "architect" in title:
        return SeniorityAssessment(
            level=SeniorityLevel.SENIOR,
            confidence=ContextConfidence.MEDIUM,
            explanation="The architect title normally carries senior individual-contributor scope.",
            evidence_quotes=[job.title],
        )

    requirement_text = " ".join(
        fact.value
        for fact in job.facts
        if fact.kind == JobFactKind.REQUIREMENT
        and canonical_key(fact.key) in {"candidate.education", "candidate.experience"}
    )
    has_education_signal = bool(requirement_text.strip())
    if not years_matches and not leadership_match:
        qualifier = " and education/experience entry evidence" if has_education_signal else ""
        return SeniorityAssessment(
            level=SeniorityLevel.JUNIOR,
            confidence=ContextConfidence.MEDIUM,
            explanation=(
                "The advertisement uses an individual-contributor title, states no minimum "
                f"years of experience or leadership responsibility{qualifier}. This supports "
                "early-career compatibility, while the formal grade remains unconfirmed."
            ),
            evidence_quotes=[job.title],
        )

    return SeniorityAssessment(
        explanation="The available advertisement evidence does not establish a seniority level."
    )


def _sentence_excerpt(text: str, position: int) -> str:
    start = max(text.rfind(".", 0, position), text.rfind("\n", 0, position)) + 1
    sentence_end = text.find(".", position)
    newline_end = text.find("\n", position)
    endings = [index for index in (sentence_end, newline_end) if index >= 0]
    end = min(endings) + 1 if endings else min(len(text), position + 220)
    return " ".join(text[start:end].split())[:2_000]


def _seniority_reason(profile_fact: ProfileFact, job: JobPosting) -> MatchReason | None:
    targets = _profile_seniority_targets(profile_fact)
    if not targets:
        return None
    assessment = _job_seniority(job)
    observed = assessment.level
    junior_group = {SeniorityLevel.INTERN, SeniorityLevel.JUNIOR}
    senior_group = {SeniorityLevel.SENIOR, SeniorityLevel.LEAD, SeniorityLevel.MANAGER}
    compatible = bool(
        observed in targets
        or (observed in junior_group and targets.intersection(junior_group))
        or (observed in senior_group and targets.intersection(senior_group))
    )
    if observed is None:
        outcome = MatchOutcome.UNKNOWN
    elif profile_fact.level == RequirementLevel.EXCLUSION:
        # Positive career targets may reasonably group adjacent levels such as
        # intern and junior. An exclusion is narrower: "no internship" must not
        # block an ordinary junior role, and "no junior role" must not silently
        # become "no early-career role of any kind". Only the evidenced level
        # named by the exclusion is a conflict.
        outcome = MatchOutcome.VIOLATED if observed in targets else MatchOutcome.SATISFIED
    elif compatible:
        outcome = (
            MatchOutcome.SUPPORTING
            if profile_fact.level == RequirementLevel.PREFERENCE
            else MatchOutcome.SATISFIED
        )
    else:
        outcome = MatchOutcome.VIOLATED
    target_labels = ", ".join(sorted(target.value for target in targets))
    observed_label = observed.value if observed else "unknown"
    if profile_fact.level == RequirementLevel.EXCLUSION:
        if observed is None:
            explanation = (
                f"Compass excludes {target_labels} roles; the available evidence does not "
                f"establish whether that exclusion applies. {assessment.explanation}"
            )
        elif outcome == MatchOutcome.VIOLATED:
            explanation = (
                f"Compass excludes {target_labels} roles; the evidence-backed role assessment "
                f"is {observed_label}, so this exclusion applies. {assessment.explanation}"
            )
        else:
            explanation = (
                f"Compass excludes {target_labels} roles; this job is assessed as "
                f"{observed_label}, so the exclusion does not apply. {assessment.explanation}"
            )
    else:
        explanation = (
            f"Compass targets {target_labels}; the evidence-backed role assessment is "
            f"{observed_label}. {assessment.explanation}"
        )
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=explanation,
        evidence_quotes=assessment.evidence_quotes,
        evidence_urls=[str(job.source_url)] if job.source_url else [],
        reasoning_confidence=assessment.confidence,
    )


def _estimated_salary_reason(
    profile_fact: ProfileFact,
    estimate: SalaryEstimate | None,
) -> MatchReason | None:
    if canonical_key(profile_fact.key) != "compensation.annual_gross" or estimate is None:
        return None
    profile_currency = _explicit_salary_currency(profile_fact.value) or "EUR"
    if profile_currency != "EUR":
        return MatchReason(
            profile_fact_id=profile_fact.id,
            profile_key=profile_fact.key,
            profile_value=str(profile_fact.value),
            outcome=MatchOutcome.UNKNOWN,
            explanation=(
                f"The available salary orientation is normalized to EUR, while your "
                f"Compass amount is in {profile_currency}. WorkLifeBalance does not apply an "
                "unstated or static exchange rate, so this salary relationship remains unknown."
            ),
            evidence_quotes=[],
            evidence_urls=[],
        )
    targets = _numbers(profile_fact.value)
    if not targets:
        return None
    target = max(targets)
    if target <= estimate.annual_min_eur:
        relationship = "The benchmark range begins above your stated amount."
    elif target <= estimate.annual_max_eur:
        relationship = "Your stated amount falls inside the benchmark range."
    else:
        relationship = "Your stated amount is above this benchmark range."
    evidence_urls = list(
        dict.fromkeys(
            [
                url
                for item in estimate.evidence
                for url in (item.source_url, item.exchange_source_url)
                if url
            ]
            or ([estimate.source_url] if estimate.source_url else [])
        )
    )
    source_quotes = list(
        dict.fromkeys(item.source_quote for item in estimate.evidence if item.source_quote)
    )
    within_orientation = target <= estimate.annual_max_eur
    is_ai_orientation = estimate.estimate_kind == SalaryEstimateKind.AI_ORIENTATION
    if within_orientation:
        # A broad market orientation is not proof of the employer's offer, so it
        # may support a target and resolve "no evidence" without ever satisfying
        # a hard boundary or creating a negative salary violation.
        outcome = MatchOutcome.SUPPORTING
    else:
        outcome = MatchOutcome.UNKNOWN
    orientation_label = (
        "very-low-confidence AI market orientation"
        if is_ai_orientation
        else "attributable market benchmark"
    )
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=(
            "The advertisement states no salary. "
            f"{relationship} This {orientation_label} may influence compatibility only as "
            "supporting context; it is not employer compensation and cannot prove a salary "
            "violation."
        ),
        evidence_quotes=[
            f"Researched market orientation: €{estimate.annual_min_eur:,}–"
            f"€{estimate.annual_max_eur:,} gross/year ({estimate.occupation_family})",
            *source_quotes,
        ],
        evidence_urls=evidence_urls,
        reasoning_confidence=(
            ContextConfidence.LOW if is_ai_orientation else ContextConfidence.MEDIUM
        ),
    )


def _employment_reason(
    profile_fact: ProfileFact,
    employer: EmployerAssessment | None,
) -> MatchReason | None:
    """Resolve direct-employer boundaries from researched context when relevant."""

    material = normalize_text(f"{profile_fact.key} {profile_fact.value}")
    direct_target = "direct" in material and any(
        marker in material for marker in ("employer", "contract", "employment")
    )
    agency_target = any(
        marker in material
        for marker in (
            "temporary agency",
            "staffing agency",
            "staffing company",
            "recruitment agency",
            "personaldienstleister",
            "zeitarbeit",
        )
    )
    employment_key = profile_fact.key.startswith("employment.")
    if employer is None or not (direct_target or agency_target or employment_key):
        return None

    is_agency = employer.kind in {
        EmployerKind.STAFFING_AGENCY,
        EmployerKind.RECRUITMENT_AGENCY,
    }
    is_direct = employer.kind == EmployerKind.DIRECT_EMPLOYER
    if profile_fact.level == RequirementLevel.EXCLUSION and (agency_target or employment_key):
        if is_agency:
            outcome = MatchOutcome.VIOLATED
            explanation = "Public employer evidence indicates staffing or recruitment activity."
        elif is_direct:
            outcome = MatchOutcome.SATISFIED
            explanation = (
                "Public employer evidence indicates a likely direct-employer relationship. "
                "Confirm the legal entity in the contract before signing."
            )
        else:
            outcome = MatchOutcome.UNKNOWN
            explanation = employer.explanation
    elif direct_target or employment_key:
        if is_direct:
            outcome = MatchOutcome.SATISFIED
            explanation = (
                "The verified source and public employer evidence support a likely direct "
                "contract. Confirm the legal entity in the final offer."
            )
        elif is_agency:
            outcome = MatchOutcome.VIOLATED
            explanation = "Public employer evidence indicates an agency or recruiter relationship."
        else:
            outcome = MatchOutcome.UNKNOWN
            explanation = employer.explanation
    else:
        return None
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=explanation,
        evidence_quotes=employer.evidence_quotes,
        evidence_urls=employer.evidence_urls,
        reasoning_confidence=employer.confidence,
    )


def _preference_reason(profile_fact: ProfileFact, job: JobPosting) -> MatchReason | None:
    seniority_reason = _seniority_reason(profile_fact, job)
    if seniority_reason is not None:
        return seniority_reason
    comparable = _comparable_job_facts(profile_fact, job)
    key = canonical_key(profile_fact.key)
    profile_value = normalize_text(profile_fact.value)
    if ("limited" in profile_value or "little" in profile_value) and not any(
        marker in normalize_text(fact.value)
        for fact in comparable
        for marker in ("limited", "little", "minimal", "no consulting")
    ):
        return None

    if key == "compensation.annual_gross":
        profile_numbers = _numbers(profile_fact.value)
        matches = [
            fact
            for fact in comparable
            if profile_numbers
            and _salary_values_are_comparable(profile_fact.value, fact.value)
            and _numbers(fact.value)
            and max(_numbers(fact.value)) >= min(profile_numbers)
        ]
    elif key == "work_model.weekly_hours":
        profile_numbers = _numbers(profile_fact.value)
        matches = []
        for fact in comparable:
            job_numbers = _numbers(fact.value)
            if profile_numbers and job_numbers:
                profile_min, profile_max = min(profile_numbers), max(profile_numbers)
                job_min, job_max = min(job_numbers), max(job_numbers)
                if max(profile_min, job_min) <= min(profile_max, job_max):
                    matches.append(fact)
    else:
        matches = [
            fact
            for fact in comparable
            if semantic_similarity(profile_fact.value, fact.value) >= 0.45
        ]
    if not matches:
        return None
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=MatchOutcome.SUPPORTING,
        explanation="The advertisement contains evidence supporting this preference.",
        evidence_quotes=[fact.evidence_quote for fact in matches],
    )


def _semantic_reason(
    profile_fact: ProfileFact,
    job: JobPosting,
    assessment: SemanticMatchAssessment | None,
) -> MatchReason | None:
    """Translate only a current, server-validated relation into a match reason."""

    if (
        assessment is None
        or assessment.job_id != job.id
        or assessment.profile_fact_id != profile_fact.id
        or not evidence_is_current(assessment, job.facts)
    ):
        return None
    outcome = {
        SemanticFitOutcome.SATISFIED: MatchOutcome.SATISFIED,
        SemanticFitOutcome.VIOLATED: MatchOutcome.VIOLATED,
        SemanticFitOutcome.SUPPORTING: MatchOutcome.SUPPORTING,
        SemanticFitOutcome.UNKNOWN: MatchOutcome.UNKNOWN,
    }[assessment.outcome]
    # A low-confidence contradiction is uncertainty, never a blocker.  Keep
    # this invariant here as well as at the provider boundary so old or
    # hand-constructed result JSON cannot bypass it.
    if outcome == MatchOutcome.VIOLATED and assessment.confidence == ContextConfidence.LOW:
        outcome = MatchOutcome.UNKNOWN
    elif profile_fact.level == RequirementLevel.PREFERENCE and outcome == MatchOutcome.SATISFIED:
        outcome = MatchOutcome.SUPPORTING
    elif (
        profile_fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.EXCLUSION}
        and outcome == MatchOutcome.SUPPORTING
    ):
        outcome = MatchOutcome.SATISFIED
    facts_by_id = {fact.id: fact for fact in job.facts}
    evidence = [
        facts_by_id[fact_id]
        for fact_id in assessment.evidence_job_fact_ids
        if fact_id in facts_by_id
    ]
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=assessment.explanation,
        evidence_quotes=[fact.evidence_quote for fact in evidence],
        evidence_urls=[str(job.source_url)] if job.source_url and evidence else [],
        reasoning_confidence=assessment.confidence,
        ai_assisted=True,
    )


def _semantic_fallback(
    deterministic: MatchReason | None,
    profile_fact: ProfileFact,
    job: JobPosting,
    assessment: SemanticMatchAssessment | None,
) -> MatchReason | None:
    """Use semantics only when the deterministic matcher remains unresolved."""

    if deterministic is not None and deterministic.outcome != MatchOutcome.UNKNOWN:
        return deterministic
    return _semantic_reason(profile_fact, job, assessment) or deterministic


def _demote_low_confidence_violation(reason: MatchReason) -> MatchReason:
    if (
        reason.outcome == MatchOutcome.VIOLATED
        and reason.reasoning_confidence == ContextConfidence.LOW
        and not reason.user_overridden
    ):
        return reason.model_copy(
            update={
                "outcome": MatchOutcome.UNKNOWN,
                "explanation": (
                    f"{reason.explanation} The contradiction is low confidence, so it remains "
                    "unresolved and cannot block this job."
                ),
            }
        )
    return reason


def _required_skill_coverage(
    profile: CandidateProfile,
    job: JobPosting,
) -> tuple[list[str], list[str]]:
    required = [
        fact
        for fact in job.facts
        if canonical_key(fact.key)
        in {
            "skill.name",
            "skill.programming_language",
            "programming.language",
            "language.spoken",
            "language.proficiency",
        }
        and fact.kind == JobFactKind.REQUIREMENT
    ]
    explicit_languages = _explicit_language_requirements(job)
    if explicit_languages:
        required = [fact for fact in required if not _language_only_requirement(fact.value)]
        required.extend(explicit_languages)
    required = list({fact.value.casefold(): fact for fact in required}.values())
    evidence_values = _candidate_evidence_values(profile)
    matched: list[str] = []
    missing: list[str] = []
    for requirement in required:
        if _mentioned_languages(requirement.value):
            target = (
                matched
                if _language_requirement_matches(requirement.value, evidence_values)
                else missing
            )
            target.append(requirement.value)
            continue
        if mentioned_programming_languages(requirement.value):
            alternatives = _skill_alternatives(requirement.value)
            matched_options = [
                option
                for option in alternatives
                if _programming_language_requirement_matches(option, evidence_values)
            ]
            matched_option = max(
                matched_options,
                key=lambda option: len(normalize_text(option)),
                default=None,
            )
            if matched_option is not None and _programming_language_requirement_matches(
                requirement.value,
                evidence_values,
            ):
                matched.append(
                    requirement.value
                    if len(alternatives) == 1
                    else f"One of {' / '.join(alternatives)} (matched: {matched_option})"
                )
            else:
                missing.append(
                    requirement.value
                    if len(alternatives) == 1
                    else f"One of {' / '.join(alternatives)}"
                )
            continue
        alternatives = _skill_alternatives(requirement.value)
        option_scores = (
            [
                (
                    max(semantic_similarity(option, evidence) for evidence in evidence_values),
                    option,
                )
                for option in alternatives
            ]
            if evidence_values
            else []
        )
        best_score, matched_option = max(option_scores, default=(0.0, None))
        if best_score < 0.5:
            matched_option = None
        if matched_option is not None:
            matched.append(
                requirement.value
                if len(alternatives) == 1
                else f"One of {' / '.join(alternatives)} (matched: {matched_option})"
            )
        else:
            missing.append(
                requirement.value
                if len(alternatives) == 1
                else f"One of {' / '.join(alternatives)}"
            )
    return matched, missing


def _candidate_evidence_values(profile: CandidateProfile) -> list[str]:
    return list(
        dict.fromkeys(
            str(value)
            for fact in profile.confirmed_candidate_evidence
            for value in (fact.value, fact.source.text)
            if str(value).strip()
        )
    )


def _stored_skill_requirement(value: str) -> str:
    """Recover the original requirement from a presentation-friendly result label."""

    clean = value.strip()
    if clean.startswith("One of "):
        clean = clean.removeprefix("One of ").split(" (matched:", 1)[0]
        return clean.replace(" / ", " or ")
    return clean


def skill_is_evidenced_by_profile(profile: CandidateProfile, requirement: str) -> bool:
    """Re-evaluate one displayed skill against the persona's current Compass.

    Job Detail calls this on every request.  A marker therefore follows the
    active persona evidence instead of becoming stale when a Compass fact is
    removed after an earlier Match run.
    """

    requirement = _stored_skill_requirement(requirement)
    evidence_values = _candidate_evidence_values(profile)
    if _mentioned_languages(requirement):
        return _language_requirement_matches(requirement, evidence_values)
    if mentioned_programming_languages(requirement):
        return _programming_language_requirement_matches(requirement, evidence_values)
    alternatives = _skill_alternatives(requirement)
    return any(
        semantic_similarity(option, evidence) >= 0.5
        for option in alternatives
        for evidence in evidence_values
    )


def _remote_only_mobility_reason(profile_fact: ProfileFact) -> MatchReason:
    mode_limit = mobility_limit_from_fact(profile_fact)
    mode_label = mobility_mode_label(mode_limit[0]) if mode_limit else "travel"
    outcome = (
        MatchOutcome.SATISFIED
        if profile_fact.level == RequirementLevel.MUST_HAVE
        else MatchOutcome.SUPPORTING
    )
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=(
            "This advertisement is explicitly remote-only, so no regular "
            f"{mode_label} commute is required. WorkLifeBalance credits three of the "
            "usual four mobility points without calling a route provider."
        ),
        evidence_quotes=["Explicit remote-only workplace"],
    )


def _remote_only_work_model_reason(profile_fact: ProfileFact) -> MatchReason:
    if profile_fact.level == RequirementLevel.EXCLUSION:
        outcome = MatchOutcome.VIOLATED
        explanation = "This role is explicitly remote-only and conflicts with this exclusion."
    elif profile_fact.level == RequirementLevel.MUST_HAVE:
        outcome = MatchOutcome.SATISFIED
        explanation = "This role is explicitly remote-only and satisfies this must-have."
    else:
        outcome = MatchOutcome.SUPPORTING
        explanation = "This role is explicitly remote-only and supports this preference."
    return MatchReason(
        profile_fact_id=profile_fact.id,
        profile_key=profile_fact.key,
        profile_value=str(profile_fact.value),
        outcome=outcome,
        explanation=explanation,
        evidence_quotes=["Explicit remote-only workplace"],
    )


_SPOKEN_LANGUAGE_NAMES = {
    language: spoken_language_aliases(language) for language in SPOKEN_LANGUAGES
}


def _explicit_language_requirements(job: JobPosting) -> list[JobFact]:
    """Recover explicit spoken-language requirements the extractor may omit."""

    requirements: list[JobFact] = []
    sentences = re.split(r"(?<=[.!?])\s+|[\r\n]+", job.source_text)
    requirement_markers = re.compile(
        r"\b(?:required|must|fluent|proficient|business[- ]fluent|"
        r"verhandlungssicher|flie(?:ss|ß)end\w*|kenntnisse|erforderlich|"
        r"minimum|at least|b[12]|c[12])\b",
        re.I,
    )
    for sentence in sentences:
        if not requirement_markers.search(sentence):
            continue
        for language, aliases in _SPOKEN_LANGUAGE_NAMES.items():
            match = re.search(
                rf"\b(?:{'|'.join(re.escape(alias) for alias in aliases)})"
                rf"(?:kenntnisse|kenntnis)?\b",
                sentence,
                flags=re.I,
            )
            if match is None:
                continue
            level = re.search(r"\b[ABC][12]\b", sentence, flags=re.I)
            fluent = re.search(
                r"\b(?:fluent|business[- ]fluent|verhandlungssicher|flie(?:ss|ß)end\w*)\b",
                sentence,
                flags=re.I,
            )
            practical_level = re.search(
                r"\b(?:beginner|intermediate|professional|native)(?:[- ]level)?\b",
                sentence,
                flags=re.I,
            )
            if level:
                value = f"{language} ({level.group(0).upper()})"
            elif practical_level:
                practical_name = re.split(r"[- ]", practical_level.group(0), maxsplit=1)[0]
                value = f"{language} ({practical_name.lower()})"
            elif fluent:
                value = f"{language} (fluent)"
            else:
                value = language
            requirements.append(
                JobFact(
                    key="skill.name",
                    value=value,
                    kind=JobFactKind.REQUIREMENT,
                    evidence_quote=" ".join(sentence.split())[:2_000],
                )
            )
    return requirements


_LANGUAGE_LEVELS = {
    "beginner": 1,
    "intermediate": 3,
    "professional": 5,
    "a1": 1,
    "a2": 2,
    "b1": 3,
    "b2": 4,
    "c1": 5,
    "c2": 6,
    "proficient": 4,
    "fluent": 5,
    "business fluent": 5,
    "business-fluent": 5,
    "fließend": 5,
    "fliessend": 5,
    "verhandlungssicher": 5,
    "bilingual": 6,
    "native": 6,
    "muttersprache": 6,
    "muttersprachlich": 6,
}


def _mentioned_languages(value: object) -> dict[str, int | None]:
    material = str(value)
    normalized = normalize_text(material)
    found: dict[str, int | None] = {}
    for language, aliases in _SPOKEN_LANGUAGE_NAMES.items():
        alias_match = None
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if not normalized_alias:
                continue
            alias_match = re.search(
                rf"\b{re.escape(normalized_alias)}\b",
                normalized,
            )
            if alias_match is not None:
                break
        if alias_match is None:
            continue
        levels: list[tuple[int, int]] = []
        for marker, numeric in _LANGUAGE_LEVELS.items():
            for match in re.finditer(rf"\b{re.escape(normalize_text(marker))}\b", normalized):
                distance = min(
                    abs(match.start() - alias_match.start()), abs(match.end() - alias_match.end())
                )
                levels.append((distance, numeric))
        found[language] = min(levels, default=(0, None), key=lambda item: item[0])[1]
    return found


def _language_requirement_matches(requirement: str, evidence_values: list[str]) -> bool:
    """Match explicit language presence while treating stated levels as soft evidence.

    A candidate-entered practical level and an employer's CEFR wording are not
    calibrated measurements of one another.  Presence is therefore decisive for
    skill coverage; the advertised level remains visible in the result label for
    the candidate to judge instead of becoming an automatic blocker.
    """

    required = _mentioned_languages(requirement)
    if not required:
        return False
    evidenced: set[str] = set()
    for value in evidence_values:
        evidenced.update(_mentioned_languages(value))
    if len(required) > 1 and re.search(r"(?:\bor\b|/)", requirement, flags=re.IGNORECASE):
        return bool(set(required).intersection(evidenced))
    return set(required).issubset(evidenced)


def _programming_language_requirement_matches(
    requirement: str,
    evidence_values: list[str],
) -> bool:
    """Compare named programming languages exactly and keep proficiency soft."""

    required = mentioned_programming_languages(requirement)
    if not required:
        return False
    evidenced = {
        language for value in evidence_values for language in mentioned_programming_languages(value)
    }
    if len(required) > 1 and re.search(r"(?:\bor\b|/)", requirement, flags=re.IGNORECASE):
        return bool(required.intersection(evidenced))
    return required.issubset(evidenced)


def _language_only_requirement(value: str) -> bool:
    languages = _mentioned_languages(value)
    if not languages:
        return False
    remaining = _tokens(value)
    for aliases in _SPOKEN_LANGUAGE_NAMES.values():
        for alias in aliases:
            remaining -= _tokens(alias)
    remaining -= {
        "business",
        "communication",
        "fluent",
        "language",
        "languages",
        "native",
        "proficient",
        "spoken",
        "written",
        "verhandlungssicher",
    }
    remaining -= set(_LANGUAGE_LEVELS)
    return not remaining


def _skill_alternatives(value: str) -> list[str]:
    """Keep explicit OR requirements as one requirement satisfied by any option."""

    if not re.search(r"(?:,\s*)?\bor\b", value, flags=re.IGNORECASE):
        return [value]
    options = [
        item.strip(" .")
        for item in re.split(r"\s*,\s*|\s+or\s+", value, flags=re.IGNORECASE)
        if item.strip(" .")
    ]
    generic_tokens = {
        "comparable",
        "equivalent",
        "language",
        "languages",
        "programming",
        "similar",
        "technology",
        "technologies",
    }
    concrete = [
        option
        for option in options
        if not _tokens(option) or not _tokens(option).issubset(generic_tokens)
    ]
    return concrete or [value]


def _deduplicate_violated_reasons(reasons: list[MatchReason]) -> list[MatchReason]:
    unique: list[MatchReason] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for reason in reasons:
        if reason.outcome != MatchOutcome.VIOLATED:
            unique.append(reason)
            continue
        signature = (canonical_key(reason.profile_key), tuple(reason.evidence_quotes))
        if signature not in seen:
            seen.add(signature)
            unique.append(reason)
    return unique


def _commute_reason(assessment: CommuteAssessment) -> MatchReason:
    mode_label = mobility_mode_label(assessment.mode)
    within_limit = assessment.within_limit
    if within_limit is True:
        outcome = (
            MatchOutcome.SATISFIED
            if assessment.level == RequirementLevel.MUST_HAVE
            else MatchOutcome.SUPPORTING
        )
        explanation = f"The calculated {mode_label} commute is within the stated limit."
    elif within_limit is False and assessment.level == RequirementLevel.MUST_HAVE:
        outcome = MatchOutcome.VIOLATED
        explanation = f"The calculated {mode_label} commute exceeds the stated limit."
    else:
        outcome = MatchOutcome.UNKNOWN
        if (
            assessment.estimate.status == CommuteStatus.AVAILABLE
            and assessment.unresolved_destinations
        ):
            explanation = (
                "The shortest calculated commute exceeds the stated limit, but at least one "
                "other advertised workplace could not be evaluated. The limit is not treated "
                "as violated until every alternative is known."
            )
        else:
            explanation = {
                CommuteStatus.NO_ROUTE: "No route was returned for this travel mode.",
                CommuteStatus.PROVIDER_UNAVAILABLE: (
                    "Travel time is unknown because no mobility provider is configured."
                ),
                CommuteStatus.PROVIDER_ERROR: "Travel time could not be calculated reliably.",
                CommuteStatus.NEEDS_PRECISE_LOCATION: (
                    "Travel time remains unknown because the city-level endpoints need a district, "
                    "postcode, station, or street."
                ),
                CommuteStatus.AVAILABLE: (
                    "The calculated commute does not support this preference."
                ),
            }[assessment.estimate.status]
    duration = assessment.estimate.duration_minutes
    evidence = (
        [f"{duration} minutes by {mode_label} from {assessment.origin} to {assessment.destination}"]
        if duration is not None
        else []
    )
    automatic_outcome = None
    user_overridden = assessment.user_override_minutes is not None
    if user_overridden:
        automatic_duration = assessment.automatic_duration_minutes
        if automatic_duration is None:
            automatic_outcome = MatchOutcome.UNKNOWN
        elif automatic_duration <= assessment.maximum_minutes:
            automatic_outcome = (
                MatchOutcome.SATISFIED
                if assessment.level == RequirementLevel.MUST_HAVE
                else MatchOutcome.SUPPORTING
            )
        elif assessment.level == RequirementLevel.MUST_HAVE:
            automatic_outcome = MatchOutcome.VIOLATED
        else:
            automatic_outcome = MatchOutcome.UNKNOWN
        explanation = (
            "User travel-time correction applied. The automatic provider value remains "
            "visible for comparison, while the corrected minutes drive this boundary."
        )
        evidence = [
            *evidence,
            f"User-corrected duration: {assessment.user_override_minutes} minutes",
        ]
    return MatchReason(
        profile_fact_id=assessment.profile_fact_id,
        profile_key=assessment.profile_key,
        profile_value=assessment.profile_value,
        outcome=outcome,
        explanation=explanation,
        evidence_quotes=evidence,
        automatic_outcome=automatic_outcome,
        user_overridden=user_overridden,
        user_override_note=("Manual travel-time correction" if user_overridden else None),
    )


def _apply_reason_overrides(
    reasons: list[MatchReason],
    overrides: list[JobEvidenceOverride],
) -> list[MatchReason]:
    values = {
        ReasonOverrideValue.POSITIVE: MatchOutcome.SATISFIED,
        ReasonOverrideValue.VIOLATED: MatchOutcome.VIOLATED,
        ReasonOverrideValue.UNKNOWN: MatchOutcome.UNKNOWN,
    }
    by_target = {
        item.target_key: item
        for item in overrides
        if item.kind == JobEvidenceOverrideKind.REASON and item.reason_value is not None
    }
    result: list[MatchReason] = []
    for reason in reasons:
        override = by_target.get(str(reason.profile_fact_id))
        if override is None or override.reason_value is None:
            result.append(reason)
            continue
        result.append(
            reason.model_copy(
                update={
                    "automatic_outcome": reason.outcome,
                    "outcome": values[override.reason_value],
                    "user_overridden": True,
                    "user_override_note": override.note,
                    "explanation": (
                        "User correction replaces the automatic evidence outcome for this "
                        "persona and job; the automatic value remains visible for comparison."
                    ),
                }
            )
        )
    return result


def _apply_commute_overrides(
    commutes: list[CommuteAssessment],
    overrides: list[JobEvidenceOverride],
) -> list[CommuteAssessment]:
    by_target = {
        item.target_key: item
        for item in overrides
        if item.kind == JobEvidenceOverrideKind.COMMUTE_MINUTES and item.commute_minutes is not None
    }
    return [
        assessment.model_copy(
            update={
                "user_override_minutes": override.commute_minutes,
                "automatic_duration_minutes": assessment.estimate.duration_minutes,
            }
        )
        if (override := by_target.get(str(assessment.profile_fact_id))) is not None
        else assessment
        for assessment in commutes
    ]


def _apply_skill_overrides(
    matched: list[str],
    missing: list[str],
    overrides: list[JobEvidenceOverride],
) -> tuple[list[str], list[str], list[str], list[str]]:
    matched_values = list(matched)
    missing_values = list(missing)
    forced_matched: list[str] = []
    forced_missing: list[str] = []
    for override in overrides:
        if override.kind != JobEvidenceOverrideKind.SKILL or override.skill_value is None:
            continue
        target = override.target_key.casefold()
        matched_values = [value for value in matched_values if value.casefold() != target]
        missing_values = [value for value in missing_values if value.casefold() != target]
        if override.skill_value == SkillOverrideValue.MATCHED:
            matched_values.append(override.target_label)
            forced_matched.append(override.target_label)
        else:
            missing_values.append(override.target_label)
            forced_missing.append(override.target_label)
    return matched_values, missing_values, forced_matched, forced_missing


def assess_job_posting_date(
    job: JobPosting,
    overrides: list[JobEvidenceOverride],
    *,
    evaluated_on: date,
) -> PostingDateAssessment:
    """Resolve automatic and private date context without mutating either."""

    automatic_freshness = classify_posting_date(
        job.posting_date,
        evaluated_on=evaluated_on,
    )
    user_override = next(
        (
            override
            for override in reversed(overrides)
            if override.kind == JobEvidenceOverrideKind.POSTING_DATE
            and override.posting_date is not None
        ),
        None,
    )
    effective_date = user_override.posting_date if user_override else job.posting_date
    freshness = classify_posting_date(effective_date, evaluated_on=evaluated_on)
    return PostingDateAssessment(
        automatic_date=job.posting_date,
        effective_date=effective_date,
        automatic_freshness=automatic_freshness,
        freshness=freshness,
        evaluated_on=evaluated_on,
        source=job.posting_date_source,
        confidence=job.posting_date_confidence,
        evidence_quote=job.posting_date_evidence_quote,
        user_overridden=user_override is not None,
        score_adjustment=posting_date_score_adjustment(freshness),
    )


CONTEXT_EMPLOYER_RELATIONSHIP = "employer.relationship.kind"
CONTEXT_COMPANY_REVENUE_MODEL = "company.product.revenue_model"
CONTEXT_COMPANY_SUMMARY = "company.product.summary"
CONTEXT_COMPANY_CATEGORIES = "company.product.categories"
CONTEXT_EMPLOYER_TYPES = "company.employer.types"
CONTEXT_COMPANY_NAME = "company.identity.name"
CONTEXT_REPUTATION_SUMMARY = "employer.reputation.summary"
CONTEXT_SALARY_RANGE = "salary.orientation.annual_range_eur"
CONTEXT_WORK_MODE_PREFIX = "work_mode."


def context_evidence_corrections(
    overrides: list[JobEvidenceOverride],
) -> list[ContextEvidenceCorrection]:
    """Expose every persisted contextual correction without mutating evidence."""

    return [
        ContextEvidenceCorrection(
            target_key=override.target_key,
            target_label=override.target_label,
            user_value=override.text_value,
        )
        for override in overrides
        if override.kind == JobEvidenceOverrideKind.CONTEXT and override.text_value is not None
    ]


def _apply_context_overrides(
    context: JobContext | None,
    overrides: list[JobEvidenceOverride],
) -> JobContext | None:
    """Build an effective private context while retaining the automatic model.

    Unknown keys remain persisted and visible through
    :func:`context_evidence_corrections`; only stable typed keys are interpreted
    by Matching. This keeps the generic correction layer forward-compatible
    without allowing arbitrary text to silently change the score.
    """

    if context is None:
        return None
    values = {
        override.target_key: override.text_value
        for override in overrides
        if override.kind == JobEvidenceOverrideKind.CONTEXT and override.text_value is not None
    }
    employer = context.employer
    if raw_kind := values.get(CONTEXT_EMPLOYER_RELATIONSHIP):
        try:
            kind = EmployerKind(raw_kind)
        except ValueError:
            pass
        else:
            employer = employer.model_copy(
                update={
                    "kind": kind,
                    "likely_direct_contract": kind.likely_direct_contract,
                }
            )

    intelligence = context.company_intelligence
    if intelligence is not None:
        product = intelligence.product
        product_updates = {}
        if value := values.get(CONTEXT_COMPANY_REVENUE_MODEL):
            product_updates["revenue_model"] = value
        if value := values.get(CONTEXT_COMPANY_SUMMARY):
            product_updates["summary"] = value
        if value := values.get(CONTEXT_COMPANY_CATEGORIES):
            product_updates["categories"] = [
                part for part in (item.strip() for item in value.split(",")) if part
            ]
        if value := values.get(CONTEXT_EMPLOYER_TYPES):
            employer_types = [
                part.replace("_", " ")
                for part in (item.strip() for item in value.split(","))
                if part
            ]
            product_updates["categories"] = list(
                dict.fromkeys(
                    [*product_updates.get("categories", product.categories), *employer_types]
                )
            )
        if product_updates:
            product = product.model_copy(update=product_updates)
        reputation = intelligence.reputation
        if value := values.get(CONTEXT_REPUTATION_SUMMARY):
            reputation = reputation.model_copy(update={"summary": value})
        intelligence = intelligence.model_copy(
            update={"product": product, "reputation": reputation}
        )
    work_mode_facts = []
    for fact in context.work_mode_facts:
        corrected = values.get(f"{CONTEXT_WORK_MODE_PREFIX}{fact.key}")
        work_mode_facts.append(fact.model_copy(update={"value": corrected}) if corrected else fact)
    return context.model_copy(
        update={
            "employer": employer,
            "company_intelligence": intelligence,
            "work_mode_facts": work_mode_facts,
        }
    )


def _apply_salary_override(
    estimate: SalaryEstimate | None,
    overrides: list[JobEvidenceOverride],
) -> SalaryEstimate | None:
    value = next(
        (
            item.text_value
            for item in overrides
            if item.kind == JobEvidenceOverrideKind.CONTEXT
            and item.target_key == CONTEXT_SALARY_RANGE
            and item.text_value
        ),
        None,
    )
    if value is None:
        return estimate
    match = re.fullmatch(r"\s*(\d{1,7})\s*:\s*(\d{1,7})\s*", value)
    if match is None:
        return estimate
    annual_min, annual_max = (int(part) for part in match.groups())
    if annual_min < 1 or annual_max < annual_min or annual_max > 1_000_000:
        return estimate
    basis = estimate or SalaryEstimate(
        occupation_family="User researched orientation",
        annual_min_eur=annual_min,
        annual_max_eur=annual_max,
        confidence=SalaryConfidence.VERY_LOW,
        source_label="Your private correction",
        assumption="Private user-researched annual gross salary orientation.",
        estimate_kind=SalaryEstimateKind.USER_CORRECTION,
    )
    return basis.model_copy(
        update={
            "annual_min_eur": annual_min,
            "annual_max_eur": annual_max,
            "source_label": "Your private correction",
            "source_url": None,
            "assumption": (
                "Your private annual gross salary correction. The immutable automatic "
                "orientation remains visible beside it."
            ),
            "estimate_kind": SalaryEstimateKind.USER_CORRECTION,
            "evidence": (),
        }
    )


EMPLOYER_REPUTATION_ADJUSTMENTS = {
    0: -100,
    1: -16,
    2: -8,
    3: 0,
    4: 4,
    5: 8,
}

JOB_RATING_ADJUSTMENTS = {
    0: -100,
    1: -12,
    2: -6,
    3: 0,
    4: 4,
    5: 8,
}

SOLID_MATCH_CALIBRATION_CAP = 3


def solid_match_calibration_bonus(
    *,
    satisfied_hard_requirements: int,
    supporting_preferences: int,
    matched_required_skills: int,
    hard_violations: int,
    violated_exclusion: bool,
) -> int:
    """Return a transparent, tightly bounded lift for corroborated positive fit.

    Each independently positive hard requirement, preference, or required skill
    contributes one point, capped at three. Any hard violation or exclusion
    violation disables the lift. Evidence blocker rules and the separate 0–5
    star compatibility adjustments therefore remain independent.
    """

    if hard_violations or violated_exclusion:
        return 0
    positive_signals = max(0, satisfied_hard_requirements)
    positive_signals += max(0, supporting_preferences)
    positive_signals += max(0, matched_required_skills)
    return min(SOLID_MATCH_CALIBRATION_CAP, positive_signals)


def assess_employer_reputation(stars: int | None) -> EmployerReputationImpact | None:
    """Translate a private feeling into a compatibility-only score rule."""

    if stars is None:
        return None
    if isinstance(stars, bool) or stars not in EMPLOYER_REPUTATION_ADJUSTMENTS:
        raise ValueError("employer reputation must be an explicit rating from 0 to 5")
    return EmployerReputationImpact(
        stars=stars,
        score_adjustment=EMPLOYER_REPUTATION_ADJUSTMENTS[stars],
        hard_blocker=False,
    )


def assess_job_rating(stars: int | None) -> JobRatingImpact | None:
    """Translate a compatibility feeling; ``None`` remains neutral/unrated."""

    if stars is None:
        return None
    if isinstance(stars, bool) or stars not in JOB_RATING_ADJUSTMENTS:
        raise ValueError("job rating must be an explicit rating from 0 to 5")
    return JobRatingImpact(
        stars=stars,
        score_adjustment=JOB_RATING_ADJUSTMENTS[stars],
        hard_blocker=False,
    )


def _score_section(
    key: str,
    label: str,
    positive_capacity: int,
    applied_points: int,
    mechanics: str,
    *,
    can_block: bool = False,
) -> ScoreInfluenceSection:
    total_positive_capacity = 65
    return ScoreInfluenceSection(
        key=key,
        label=label,
        positive_capacity_points=positive_capacity,
        positive_capacity_share_percent=round(
            positive_capacity * 100 / total_positive_capacity,
            2,
        ),
        applied_points=applied_points,
        mechanics=mechanics,
        can_block=can_block,
    )


def match_job(
    profile: CandidateProfile,
    job: JobPosting,
    *,
    commutes: list[CommuteAssessment] | None = None,
    context: JobContext | None = None,
    salary_evidence: list[SalaryEvidence] | None = None,
    salary_guess: SalaryGuess | None = None,
    reused_automatic_salary_estimate: SalaryEstimate | None = None,
    automatic_salary_estimate_is_reused: bool = False,
    job_overrides: list[JobEvidenceOverride] | None = None,
    employer_reputation_stars: int | None = None,
    job_rating_stars: int | None = None,
    semantic_assessments: list[SemanticMatchAssessment] | None = None,
    evaluated_at: datetime | None = None,
) -> MatchResult:
    """Match one job without letting an LLM decide filters or scores."""

    job_overrides = job_overrides or []
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    posting_date = assess_job_posting_date(
        job,
        job_overrides,
        evaluated_on=evaluated_at.astimezone(timezone.utc).date(),
    )
    effective_context = _apply_context_overrides(context, job_overrides)
    context_corrections = context_evidence_corrections(job_overrides)
    employer_reputation = assess_employer_reputation(employer_reputation_stars)
    job_rating = assess_job_rating(job_rating_stars)
    commutes = _apply_commute_overrides(commutes or [], job_overrides)
    automatic_context_facts = context.work_mode_facts if context else []
    context_facts = effective_context.work_mode_facts if effective_context else []
    contextual_job = job.model_copy(update={"facts": [*job.facts, *context_facts]})
    automatic_contextual_job = job.model_copy(
        update={"facts": [*job.facts, *automatic_context_facts]}
    )
    semantic_assessments = [
        assessment for assessment in (semantic_assessments or []) if assessment.job_id == job.id
    ]
    semantic_by_profile_fact_id = {
        assessment.profile_fact_id: assessment for assessment in semantic_assessments
    }
    remote_only = job_is_remote_only(contextual_job)
    remote_excluded = remote_only and any(
        fact.level == RequirementLevel.EXCLUSION and canonical_key(fact.key) == "work_model.remote"
        for fact in profile.confirmed_search_facts
    )
    remote_mobility_facts = [
        fact
        for fact in profile.confirmed_search_facts
        if remote_only
        and mobility_limit_from_fact(fact) is not None
        and fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.PREFERENCE}
    ]
    remote_mobility_fact_ids = {fact.id for fact in remote_mobility_facts}
    automatic_salary_estimate = (
        reused_automatic_salary_estimate
        if automatic_salary_estimate_is_reused
        else estimate_salary(
            automatic_contextual_job,
            salary_evidence,
            salary_guess,
        )
    )
    salary_estimate = _apply_salary_override(automatic_salary_estimate, job_overrides)
    commute_fact_ids = {assessment.profile_fact_id for assessment in commutes}
    hard_facts = [
        fact
        for fact in profile.confirmed_search_facts
        if fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.EXCLUSION}
        and fact.id not in commute_fact_ids
        and fact.id not in remote_mobility_fact_ids
        and canonical_key(fact.key) not in PROFILE_CONTEXT_ONLY_KEYS
    ]
    commute_reasons = [_commute_reason(assessment) for assessment in commutes]
    hard_reasons = [
        *[
            _semantic_fallback(
                _estimated_salary_reason(fact, salary_estimate)
                or (
                    _remote_only_work_model_reason(fact)
                    if remote_only and canonical_key(fact.key) == "work_model.remote"
                    else None
                )
                or _hard_reason(
                    fact,
                    contextual_job,
                    effective_context.employer if effective_context else None,
                    effective_context.company_intelligence if effective_context else None,
                ),
                fact,
                contextual_job,
                semantic_by_profile_fact_id.get(fact.id),
            )
            for fact in hard_facts
        ],
        *[
            reason
            for assessment, reason in zip(commutes, commute_reasons, strict=True)
            if assessment.level == RequirementLevel.MUST_HAVE
        ],
        *(
            [
                _remote_only_mobility_reason(fact)
                for fact in remote_mobility_facts
                if fact.level == RequirementLevel.MUST_HAVE
            ]
            if not remote_excluded
            else []
        ),
    ]
    hard_reasons = [_demote_low_confidence_violation(reason) for reason in hard_reasons]
    hard_reasons = _apply_reason_overrides(hard_reasons, job_overrides)
    violation_signatures = {
        (canonical_key(reason.profile_key), tuple(reason.evidence_quotes))
        for reason in hard_reasons
        if reason.outcome == MatchOutcome.VIOLATED
    }
    hard_violations = len(violation_signatures)
    satisfied_hard = sum(reason.outcome == MatchOutcome.SATISFIED for reason in hard_reasons)
    unknown_hard = sum(reason.outcome == MatchOutcome.UNKNOWN for reason in hard_reasons)
    known_hard = len(hard_reasons) - unknown_hard
    hard_evidence_coverage = round(100 * known_hard / len(hard_reasons)) if hard_reasons else 100
    must_have_ids = {
        fact.id
        for fact in [*hard_facts, *remote_mobility_facts]
        if fact.level == RequirementLevel.MUST_HAVE
    }
    must_have_ids.update(
        assessment.profile_fact_id
        for assessment in commutes
        if assessment.level == RequirementLevel.MUST_HAVE
    )
    exclusion_ids = {fact.id for fact in hard_facts if fact.level == RequirementLevel.EXCLUSION}
    violated_exclusion = any(
        reason.outcome == MatchOutcome.VIOLATED and reason.profile_fact_id in exclusion_ids
        for reason in hard_reasons
    )
    blocking_hard_violation = any(
        reason.outcome == MatchOutcome.VIOLATED
        and reason.profile_fact_id in must_have_ids.union(exclusion_ids)
        and (
            reason.user_overridden
            or reason.reasoning_confidence
            in {None, ContextConfidence.MEDIUM, ContextConfidence.HIGH}
        )
        for reason in hard_reasons
    )
    preference_reasons = [
        reason
        for fact in profile.confirmed_search_facts
        if fact.level == RequirementLevel.PREFERENCE
        if fact.id not in commute_fact_ids
        if fact.id not in remote_mobility_fact_ids
        if canonical_key(fact.key) not in PROFILE_CONTEXT_ONLY_KEYS
        if (
            reason := _semantic_fallback(
                (
                    _remote_only_work_model_reason(fact)
                    if remote_only and canonical_key(fact.key) == "work_model.remote"
                    else None
                )
                or _preference_reason(fact, contextual_job)
                or _company_preference_reason(
                    fact,
                    effective_context.company_intelligence if effective_context else None,
                )
                or _estimated_salary_reason(fact, salary_estimate),
                fact,
                contextual_job,
                semantic_by_profile_fact_id.get(fact.id),
            )
        )
        is not None
    ]
    preference_reasons.extend(
        reason
        for assessment, reason in zip(commutes, commute_reasons, strict=True)
        if assessment.level == RequirementLevel.PREFERENCE
        and reason.outcome == MatchOutcome.SUPPORTING
    )
    if not remote_excluded:
        preference_reasons.extend(
            _remote_only_mobility_reason(fact)
            for fact in remote_mobility_facts
            if fact.level == RequirementLevel.PREFERENCE
        )
    preference_reasons = [_demote_low_confidence_violation(reason) for reason in preference_reasons]
    preference_reasons = _apply_reason_overrides(preference_reasons, job_overrides)
    matched_skills, missing_skills = _required_skill_coverage(profile, contextual_job)
    (
        matched_skills,
        missing_skills,
        user_matched_skills,
        user_missing_skills,
    ) = _apply_skill_overrides(matched_skills, missing_skills, job_overrides)
    total_required = len(matched_skills) + len(missing_skills)
    skill_ratio = len(matched_skills) / total_required if total_required else None

    # Fit and evidence coverage are deliberately separate. An advertisement that
    # omits culture, salary, or working-time detail is uncertain, not automatically
    # a poor match. Only proven conflicts lower compatibility.
    preference_points = sum(
        3
        if reason.profile_fact_id in remote_mobility_fact_ids
        else 6
        if canonical_key(reason.profile_key)
        in {"role.family", "role.responsibility", "career.direction", "industry.sector"}
        else 4
        for reason in preference_reasons
        if reason.outcome == MatchOutcome.SUPPORTING
    )
    preference_violations = sum(
        reason.outcome == MatchOutcome.VIOLATED for reason in preference_reasons
    )
    base_points = 56
    remote_satisfied_hard = sum(
        reason.outcome == MatchOutcome.SATISFIED
        and reason.profile_fact_id in remote_mobility_fact_ids
        for reason in hard_reasons
    )
    hard_positive_points = (satisfied_hard - remote_satisfied_hard) * 4
    hard_positive_points += remote_satisfied_hard * 3
    remote_mobility_points = remote_satisfied_hard * 3 + sum(
        3
        for reason in preference_reasons
        if reason.outcome == MatchOutcome.SUPPORTING
        and reason.profile_fact_id in remote_mobility_fact_ids
    )
    compass_points = min(24, preference_points) + min(12, hard_positive_points)
    compass_points -= preference_violations * 6
    compass_points -= hard_violations * 30
    skill_points = 0
    if skill_ratio is not None:
        skill_points += round(8 * skill_ratio)
        skill_points -= round(8 * (1 - skill_ratio))
    pre_confidence_score = base_points + compass_points + skill_points

    scoring_reasons = _deduplicate_violated_reasons([*hard_reasons, *preference_reasons])
    resolved_evidence = sum(reason.outcome != MatchOutcome.UNKNOWN for reason in scoring_reasons)
    evidence_ratio = resolved_evidence / len(scoring_reasons) if scoring_reasons else 0.0
    # Compatibility and evidence coverage remain distinct, but a sparse page
    # cannot present a near-certain score. This confidence multiplier preserves
    # promising unknowns while preventing a handful of matches from yielding an
    # 80+ score. Fully evidenced results retain their complete calculated score.
    evidence_multiplier = 0.72 + 0.28 * evidence_ratio
    score_after_confidence = round(pre_confidence_score * evidence_multiplier)
    evidence_confidence_adjustment = score_after_confidence - pre_confidence_score
    reputation_adjustment = employer_reputation.score_adjustment if employer_reputation else 0
    job_rating_adjustment = job_rating.score_adjustment if job_rating else 0
    calibration_bonus = solid_match_calibration_bonus(
        satisfied_hard_requirements=satisfied_hard,
        supporting_preferences=sum(
            reason.outcome == MatchOutcome.SUPPORTING for reason in preference_reasons
        ),
        matched_required_skills=len(matched_skills),
        hard_violations=hard_violations,
        violated_exclusion=violated_exclusion,
    )
    score = score_after_confidence
    score += calibration_bonus
    score += posting_date.score_adjustment
    score += reputation_adjustment
    score += job_rating_adjustment
    score = max(0, min(100, score))

    score_mechanics = ScoreMechanics(
        base_points=base_points,
        pre_confidence_points=pre_confidence_score,
        evidence_confidence_multiplier=evidence_multiplier,
        evidence_confidence_adjustment=evidence_confidence_adjustment,
        sections=[
            _score_section(
                "compass",
                "Compass boundaries and preferences",
                36,
                compass_points,
                (
                    "Up to +24 preference points and +12 must-have points; "
                    "preference conflicts cost 6 and hard conflicts cost 30 each. "
                    "An explicit remote-only role receives 3 rather than 4 points per "
                    "applicable commute boundary, without a route-provider call."
                ),
                can_block=True,
            ),
            _score_section(
                "skills",
                "Required skills",
                8,
                skill_points,
                "Required-skill coverage ranges deterministically from -8 to +8 points.",
            ),
            _score_section(
                "solid_match_calibration",
                "Confirmed fit signals",
                SOLID_MATCH_CALIBRATION_CAP,
                calibration_bonus,
                (
                    "Adds one point for each independently confirmed must-have, preference, "
                    "or required skill, up to +3. No bonus is added when a must-have or "
                    "exclusion conflicts. Your own ratings remain separate."
                ),
            ),
            _score_section(
                "posting_date",
                "Posting freshness",
                2,
                posting_date.score_adjustment,
                "Fresh adds 2, medium or unknown adds 0, and old subtracts 4 points.",
            ),
            _score_section(
                "employer_reputation",
                "Your employer compatibility feeling",
                8,
                reputation_adjustment,
                (
                    "Unrated has no effect; 1–5 stars adjust the score by "
                    "-16/-8/0/+4/+8. Zero stars can reduce compatibility to zero "
                    "but never create a Compass boundary."
                ),
            ),
            _score_section(
                "job_rating",
                "Your compatibility feeling about this job",
                8,
                job_rating_adjustment,
                (
                    "Unrated has no effect; 1–5 stars adjust this job by "
                    "-12/-6/0/+4/+8. Zero stars can reduce compatibility to zero "
                    "but never create a Compass boundary."
                ),
            ),
        ],
        final_points=score,
    )

    if blocking_hard_violation:
        disposition = MatchDisposition.BLOCKED
    # Evidence gaps already lower the numeric score through the published
    # confidence multiplier. Applying a second unknown-must-have gate here can
    # produce an 80-point Stretch below a 70-point Top match. For every result
    # without a confirmed blocker, the displayed group now follows the same
    # threshold as the displayed score.
    elif score >= 60:
        disposition = MatchDisposition.TOP
    else:
        disposition = MatchDisposition.STRETCH

    # Train, car, and bicycle already have a complete editable mobility
    # comparison. Repeating the same fact under "Compass checks" adds noise and
    # invites contradictory corrections. Walking and other custom travel facts
    # intentionally remain visible there.
    standard_mobility_modes = {
        TravelMode.TRANSIT,
        TravelMode.CAR,
        TravelMode.BICYCLE,
    }
    standard_mobility_fact_ids = {
        assessment.profile_fact_id
        for assessment in commutes
        if assessment.mode in standard_mobility_modes
    }
    standard_mobility_fact_ids.update(
        fact.id
        for fact in remote_mobility_facts
        if (limit := mobility_limit_from_fact(fact)) is not None
        and limit[0] in standard_mobility_modes
    )
    rendered_reasons = [
        reason
        for reason in scoring_reasons
        if reason.profile_fact_id not in standard_mobility_fact_ids
    ]

    return MatchResult(
        job_id=job.id,
        job_url=job.source_url,
        source_is_manual=job.source_type == JobSourceType.MANUAL_TEXT,
        url_status=job.url_status,
        url_http_status=job.url_http_status,
        url_verified_at=job.url_checked_at,
        score=score,
        hard_evidence_coverage=hard_evidence_coverage,
        disposition=disposition,
        hard_violations=hard_violations,
        reasons=rendered_reasons,
        semantic_assessments=semantic_assessments,
        commutes=commutes,
        matched_required_skills=matched_skills,
        missing_required_skills=missing_skills,
        user_overridden_matched_skills=user_matched_skills,
        user_overridden_missing_skills=user_missing_skills,
        employer_assessment=context.employer if context else None,
        effective_employer_assessment=(effective_context.employer if effective_context else None),
        derived_work_mode_facts=automatic_context_facts,
        effective_work_mode_facts=context_facts,
        automatic_salary_estimate=automatic_salary_estimate,
        salary_estimate=salary_estimate,
        company_intelligence=context.company_intelligence if context else None,
        effective_company_intelligence=(
            effective_context.company_intelligence if effective_context else None
        ),
        posting_date=posting_date,
        employer_reputation=employer_reputation,
        job_rating=job_rating,
        score_mechanics=score_mechanics,
        context_evidence_corrections=context_corrections,
        remote_only_mobility=remote_only,
        remote_only_excluded=remote_excluded,
        remote_mobility_points=remote_mobility_points,
        profile_fingerprint=profile_evidence_fingerprint(profile),
        source_evidence_fingerprint=job_source_evidence_fingerprint(job),
        user_evidence_fingerprint=user_evidence_fingerprint(job_overrides),
        rating_fingerprint=rating_input_fingerprint(
            employer_reputation_stars=employer_reputation_stars,
            job_rating_stars=job_rating_stars,
        ),
    )


def _unresolved_semantic_criteria(
    profile: CandidateProfile,
    job: JobPosting,
    context: JobContext | None,
) -> list[ProfileFact]:
    """Select only criteria for which deterministic matching has no answer."""

    remote_only = job_is_remote_only(job)
    unresolved: list[ProfileFact] = []
    for fact in profile.confirmed_search_facts:
        if (
            fact.level
            not in {
                RequirementLevel.MUST_HAVE,
                RequirementLevel.PREFERENCE,
                RequirementLevel.EXCLUSION,
            }
            or canonical_key(fact.key) in PROFILE_CONTEXT_ONLY_KEYS
            or canonical_key(fact.key).startswith(("location.", "commute.", "mobility."))
            or canonical_key(fact.key) == "compensation.annual_gross"
            or mobility_limit_from_fact(fact) is not None
        ):
            continue
        if fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.EXCLUSION}:
            deterministic = (
                _remote_only_work_model_reason(fact)
                if remote_only and canonical_key(fact.key) == "work_model.remote"
                else None
            ) or _hard_reason(
                fact,
                job,
                context.employer if context else None,
                context.company_intelligence if context else None,
            )
            if deterministic.outcome == MatchOutcome.UNKNOWN:
                unresolved.append(fact)
            continue
        deterministic_preference = (
            (
                _remote_only_work_model_reason(fact)
                if remote_only and canonical_key(fact.key) == "work_model.remote"
                else None
            )
            or _preference_reason(fact, job)
            or _company_preference_reason(
                fact,
                context.company_intelligence if context else None,
            )
        )
        if (
            deterministic_preference is None
            or deterministic_preference.outcome == MatchOutcome.UNKNOWN
        ):
            unresolved.append(fact)
    return unresolved


def match_jobs(
    profile: CandidateProfile,
    jobs: list[JobPosting],
    *,
    run_id: UUID | None = None,
    commutes_by_job_id: dict[UUID, list[CommuteAssessment]] | None = None,
    contexts_by_job_id: dict[UUID, JobContext] | None = None,
    salary_evidence_by_job_id: dict[UUID, list[SalaryEvidence]] | None = None,
    salary_guesses_by_job_id: dict[UUID, SalaryGuess] | None = None,
    job_overrides_by_job_id: dict[UUID, list[JobEvidenceOverride]] | None = None,
    employer_reputation_by_job_id: dict[UUID, int] | None = None,
    job_ratings_by_job_id: dict[UUID, int] | None = None,
    semantic_assessments_by_job_id: dict[UUID, list[SemanticMatchAssessment]] | None = None,
    match_evidence_resolver: MatchEvidenceResolverPort | None = None,
    evaluated_at: datetime | None = None,
) -> MatchRun:
    order = {
        MatchDisposition.TOP: 0,
        MatchDisposition.STRETCH: 1,
        MatchDisposition.BLOCKED: 2,
    }
    commutes_by_job_id = commutes_by_job_id or {}
    contexts_by_job_id = contexts_by_job_id or {}
    salary_evidence_by_job_id = salary_evidence_by_job_id or {}
    salary_guesses_by_job_id = salary_guesses_by_job_id or {}
    job_overrides_by_job_id = job_overrides_by_job_id or {}
    employer_reputation_by_job_id = employer_reputation_by_job_id or {}
    job_ratings_by_job_id = job_ratings_by_job_id or {}
    if semantic_assessments_by_job_id is None:
        semantic_assessments_by_job_id = {}
        if match_evidence_resolver is not None:
            semantic_jobs: list[JobPosting] = []
            semantic_profile_facts_by_job_id: dict[UUID, list[ProfileFact]] = {}
            for job in jobs:
                effective_context = _apply_context_overrides(
                    contexts_by_job_id.get(job.id),
                    job_overrides_by_job_id.get(job.id, []),
                )
                context_facts = effective_context.work_mode_facts if effective_context else []
                semantic_jobs.append(job.model_copy(update={"facts": [*job.facts, *context_facts]}))
                semantic_profile_facts_by_job_id[job.id] = _unresolved_semantic_criteria(
                    profile,
                    semantic_jobs[-1],
                    effective_context,
                )
            try:
                semantic_assessments_by_job_id = match_evidence_resolver.assess(
                    profile_facts_by_job_id=semantic_profile_facts_by_job_id,
                    jobs=semantic_jobs,
                )
            except Exception:
                # This optional relation pass may improve evidence coverage, but
                # unavailable or invalid provider output must fail closed to
                # UNKNOWN and never prevent deterministic Matching.
                semantic_assessments_by_job_id = {}
    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    results = [
        match_job(
            profile,
            job,
            commutes=commutes_by_job_id.get(job.id, []),
            context=contexts_by_job_id.get(job.id),
            salary_evidence=salary_evidence_by_job_id.get(job.id),
            salary_guess=salary_guesses_by_job_id.get(job.id),
            job_overrides=job_overrides_by_job_id.get(job.id, []),
            employer_reputation_stars=employer_reputation_by_job_id.get(job.id),
            job_rating_stars=job_ratings_by_job_id.get(job.id),
            semantic_assessments=semantic_assessments_by_job_id.get(job.id, []),
            evaluated_at=evaluated_at,
        )
        for job in jobs
    ]
    results.sort(key=lambda result: (order[result.disposition], -result.score))
    return MatchRun(
        id=run_id or uuid4(),
        profile_id=profile.id,
        created_at=evaluated_at,
        algorithm_version="matching-v0.7.2i",
        results=results,
    )


def save_match_run(
    run: MatchRun,
    directory: Path = Path("local-data") / "matches",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"match-run-{run.id}.json"
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    return path
