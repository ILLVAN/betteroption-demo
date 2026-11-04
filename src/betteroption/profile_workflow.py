"""Application service for the database-backed web profile conversation."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import cast
import unicodedata
from uuid import UUID

from pydantic import AnyHttpUrl, TypeAdapter

from .candidate_languages import (
    LANGUAGE_EDITOR_NOTE_PREFIX,
    PROGRAMMING_LANGUAGE_FACT_KEY,
    SPOKEN_LANGUAGE_FACT_KEY,
    PracticalProficiency,
    canonical_catalog_name,
    is_language_editor_fact,
    language_fact_value,
    mentioned_programming_languages,
    mentioned_spoken_languages,
)
from .cv import detect_prohibited_categories
from .extraction import SectionExtraction
from .job_repository import normalize_job_url
from .jobs import JobPosting
from .llm import ProfileExtractorPort
from .profile import (
    COMPENSATION_RANGE_MAX_EUR,
    COMPENSATION_RANGE_MIN_EUR,
    CandidateProfile,
    CompensationCurrency,
    Confidence,
    EvidenceStatus,
    LocationPreference,
    ProfileFact,
    ProfileSection,
    ReferenceJob,
    RequirementLevel,
    ReviewAction,
    SUPPORTED_COMPENSATION_CURRENCIES,
    SourceExcerpt,
    TravelConstraint,
    TravelMode,
    profile_fact_signature,
    set_compensation_range,
)
from .profile_mobility import (
    canonicalize_mobility_fact,
    mobility_limit_from_fact,
    mobility_mode_label,
    origin_precision_from_label,
    sync_location_projection_from_facts,
)
from .profile_repository import (
    ConversationRole,
    ProfileWorkspace,
    ProfileWorkspaceRepository,
)
from .review import accept_user_input_facts, apply_review, merge_extracted_facts
from .session import (
    SessionState,
    SectionStatus,
    complete_section_review,
    definition_for,
    leave_clarification_open,
    mark_section_skipped,
    next_clarification_section,
    next_pending_section,
    next_review_section,
    progress_for,
    record_section_extraction,
    reopen_skipped_sections,
)
from .url_ingestion import PublicUrlFetcher


class ProfileWorkflowError(RuntimeError):
    """Raised when a profile action cannot be completed safely."""


_LANGUAGE_EDITOR_PROGRESS_SUMMARY = "Candidate languages added directly in Compass."


_ANNUAL_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,3}(?:[ .,_]\d{3})+|\d{4,6}|\d{1,3}(?:[.,]\d+)?\s*[kK])(?!\d)"
)
_MINIMUM_LABEL_PATTERN = re.compile(
    r"(?:\bminimum\b|\bmin\.?|\bat\s+least\b|\bmindestens\b|\buntergrenze\b|\bab\b)"
    r"\D{0,24}"
    r"(?P<amount>\d{1,3}(?:[ .,_]\d{3})+|\d{4,6}|\d{1,3}(?:[.,]\d+)?\s*[kK])",
    flags=re.IGNORECASE,
)
_TARGET_LABEL_PATTERN = re.compile(
    r"(?:\btarget\b|\bgoal\b|\bdesired\b|\baim\b|\bziel\b|\bwunsch(?:gehalt)?\b)"
    r"\D{0,24}"
    r"(?P<amount>\d{1,3}(?:[ .,_]\d{3})+|\d{4,6}|\d{1,3}(?:[.,]\d+)?\s*[kK])",
    flags=re.IGNORECASE,
)
_COMPENSATION_CURRENCY_PATTERN = re.compile(
    rf"\b(?:{'|'.join(SUPPORTED_COMPENSATION_CURRENCIES)})\b",
    flags=re.IGNORECASE,
)
_WORD_LIKE_COMPENSATION_CURRENCIES = frozenset({"ALL", "RUB", "TRY"})


def _annual_eur_amount(token: str) -> int | None:
    material = token.strip().casefold().replace(" ", "").replace("_", "")
    multiplier = 1_000 if material.endswith("k") else 1
    material = material.removesuffix("k")
    if multiplier == 1_000:
        material = material.replace(",", ".")
        try:
            value = round(float(material) * multiplier)
        except ValueError:
            return None
    else:
        material = material.replace(".", "").replace(",", "")
        if not material.isdigit():
            return None
        value = int(material)
    if 0 <= value <= COMPENSATION_RANGE_MAX_EUR:
        return value
    return None


def _labelled_amount(pattern: re.Pattern[str], material: str) -> int | None:
    match = pattern.search(material)
    return _annual_eur_amount(match.group("amount")) if match else None


def _is_annual_compensation_fact(fact: ProfileFact) -> bool:
    if fact.source.section not in {
        ProfileSection.COMPENSATION_TIME,
        ProfileSection.MUST_HAVES,
    }:
        return False
    key = fact.key.casefold()
    return key.startswith(("compensation.", "salary.")) and any(
        marker in key
        for marker in ("annual", "gross", "salary", "minimum", "target", "desired", "goal")
    )


def _compensation_values_from_fact(fact: ProfileFact) -> tuple[int | None, int | None]:
    """Conservatively project an explicit salary fact into the typed range."""

    if not _is_annual_compensation_fact(fact):
        return None, None
    key = fact.key.casefold()
    # ``source.text`` is historical extraction evidence. Once the user edits a
    # fact, only its current value may rebuild the typed range.
    material = str(fact.value)
    minimum = _labelled_amount(_MINIMUM_LABEL_PATTERN, material)
    target = _labelled_amount(_TARGET_LABEL_PATTERN, material)
    tokens = [
        amount
        for token in _ANNUAL_AMOUNT_PATTERN.findall(str(fact.value))
        if (amount := _annual_eur_amount(token)) is not None and amount >= 5_000
    ]
    if minimum is None and any(marker in key for marker in ("minimum", "min_")):
        minimum = max(tokens, default=None)
    if target is None and any(marker in key for marker in ("target", "desired", "goal")):
        target = max(tokens, default=None)
    if minimum is None and target is None and tokens:
        if fact.level == RequirementLevel.MUST_HAVE:
            minimum = max(tokens)
        elif fact.level in {RequirementLevel.PREFERENCE, RequirementLevel.OPEN}:
            target = max(tokens)
    return minimum, target


def _compensation_currency_from_fact(fact: ProfileFact) -> CompensationCurrency | None:
    material = f"{fact.value} {fact.source.text}"
    for match in _COMPENSATION_CURRENCY_PATTERN.finditer(material):
        token = match.group(0)
        normalized = token.upper()
        if normalized in _WORD_LIKE_COMPENSATION_CURRENCIES and token != normalized:
            continue
        return cast(CompensationCurrency, normalized)
    return None


def _sync_compensation_from_fact_ids(profile: CandidateProfile, fact_ids: list[UUID]) -> None:
    selected = set(fact_ids)
    touched_compensation = any(
        fact.id in selected and _is_annual_compensation_fact(fact) for fact in profile.facts
    )
    if not touched_compensation:
        return
    minimum: int | None = None
    target: int | None = None
    currency: CompensationCurrency | None = None
    for fact in sorted(profile.facts, key=lambda item: item.created_at):
        if fact.evidence_status != EvidenceStatus.CONFIRMED:
            continue
        fact_minimum, fact_target = _compensation_values_from_fact(fact)
        minimum = fact_minimum if fact_minimum is not None else minimum
        target = fact_target if fact_target is not None else target
        if fact_minimum is not None or fact_target is not None:
            currency = _compensation_currency_from_fact(fact) or currency
    if minimum is None and target is None:
        set_compensation_range(
            profile,
            COMPENSATION_RANGE_MIN_EUR,
            None,
            currency,
        )
        return
    next_minimum = minimum if minimum is not None else COMPENSATION_RANGE_MIN_EUR
    next_target = target
    if next_target is not None and next_target < next_minimum:
        next_target = next_minimum
    set_compensation_range(profile, next_minimum, next_target, currency)


def safe_profile_extraction_diagnostic(error: Exception | None) -> str:
    """Return actionable provider diagnostics without echoing exception or secret content."""

    if error is None:
        return (
            "OpenAI structuring is not configured. Set OPENAI_API_KEY in the local .env "
            "file and restart the app."
        )
    material = f"{type(error).__name__} {error}".casefold()
    if any(
        marker in material
        for marker in (
            "api key",
            "api_key",
            "authentication",
            "unauthorized",
            "http 401",
        )
    ):
        return (
            "OpenAI authentication failed. Check that OPENAI_API_KEY in the local .env file "
            "is a current project key, then restart the app."
        )
    if any(marker in material for marker in ("insufficient_quota", "credit balance", "quota")):
        return (
            "The OpenAI project has no usable quota. Check its credit balance and project budget, "
            "then retry."
        )
    if "rate limit" in material or "ratelimit" in material:
        return "The OpenAI rate limit was reached. Wait briefly and retry."
    if any(
        marker in material
        for marker in ("connection", "connecterror", "timeout", "unreachable", "network")
    ):
        return (
            "OpenAI is unreachable. Check the internet connection, firewall, or proxy, then retry."
        )
    if any(
        marker in material
        for marker in ("not found", "model access", "http 404", "http 403", "forbidden")
    ):
        return (
            "The configured OpenAI model is unavailable to this project. Check OPENAI_MODEL and "
            "project model access."
        )
    return (
        "The configured AI provider could not structure this input. Check the provider status and "
        "the secret-safe local diagnostic before retrying."
    )


_REFERENCE_SCOPE_CONFIG: dict[
    str,
    tuple[ProfileSection, tuple[str, ...], tuple[str, ...]],
] = {
    "role": (
        ProfileSection.DIRECTION,
        ("role.", "career.", "industry.sector"),
        ("role", "task", "responsibility", "ownership", "position", "domain"),
    ),
    "skills": (
        ProfileSection.PREFERENCES,
        ("skill.", "candidate.experience", "domain.knowledge"),
        ("skill", "technology", "tool", "language", "python", "software", "hardware"),
    ),
    "culture": (
        ProfileSection.ENVIRONMENT_CULTURE,
        ("culture.",),
        (
            "culture",
            "team",
            "international",
            "calm",
            "autonomy",
            "feedback",
            "management",
            "hierarchy",
            "leadership",
            "pace",
        ),
    ),
    "location": (
        ProfileSection.LOCATION_MOBILITY,
        ("location.", "office.location", "workplace.location"),
        ("location", "city", "office", "commute", "near", "remote"),
    ),
    "work_model": (
        ProfileSection.WORKING_MODEL,
        ("work_model.", "travel.required"),
        ("hybrid", "remote", "office", "hours", "shift", "travel", "flexible"),
    ),
    "pay": (
        ProfileSection.COMPENSATION_TIME,
        ("compensation.", "contract.collective_agreement"),
        ("salary", "pay", "compensation", "bonus", "vacation", "benefit", "pension"),
    ),
}


def _reference_tokens(value: object) -> set[str]:
    material = unicodedata.normalize("NFKD", str(value).casefold())
    material = "".join(character for character in material if not unicodedata.combining(character))
    return set(re.findall(r"[a-z0-9+#]+", material)).difference(
        {"a", "an", "and", "for", "in", "of", "or", "the", "to", "with"}
    )


def _scope_fact_candidates(job: JobPosting, scope: str) -> list[tuple[str, str, str]]:
    _section, prefixes, _keywords = _REFERENCE_SCOPE_CONFIG[scope]
    return [
        (fact.key, fact.value, fact.evidence_quote)
        for fact in job.facts
        if fact.key.startswith(prefixes)
    ]


def _reference_scope_for_note(
    note: str,
    scopes: list[str],
    job: JobPosting,
) -> tuple[str, str, str | None] | None:
    note_tokens = _reference_tokens(note)
    ranked: list[tuple[float, int, str, str, str]] = []
    for scope_index, scope in enumerate(scopes):
        _section, _prefixes, keywords = _REFERENCE_SCOPE_CONFIG[scope]
        keyword_score = len(note_tokens.intersection(keywords)) / max(1, len(note_tokens))
        candidates = _scope_fact_candidates(job, scope)
        if not candidates:
            continue
        ranked_candidates = [
            (
                len(note_tokens.intersection(_reference_tokens(f"{value} {evidence}"))),
                key,
                evidence,
            )
            for key, value, evidence in candidates
        ]
        overlap, best_key, best_evidence = max(ranked_candidates)
        # A scope keyword alone is not evidence. Learning must always point to
        # a structured fact extracted from the verified job text.
        if overlap <= 0:
            continue
        evidence_score = overlap / max(1, len(note_tokens))
        ranked.append(
            (
                evidence_score + keyword_score * 0.25,
                -scope_index,
                scope,
                best_key,
                best_evidence,
            )
        )
    if not ranked:
        return None
    score, _order, scope, key, evidence = max(ranked)
    if score <= 0:
        return None
    return scope, key, evidence


def _reference_learning_proposals(reference: ReferenceJob, job: JobPosting) -> list[ProfileFact]:
    proposals: list[ProfileFact] = []
    for note in reference.positives:
        mapped = _reference_scope_for_note(note, reference.learning_scope, job)
        if mapped is None:
            continue
        scope, key, evidence = mapped
        section = _REFERENCE_SCOPE_CONFIG[scope][0]
        source_text = f"Reference note: {note}"
        source_text += f"\nVerified job evidence: {evidence}"
        proposals.append(
            ProfileFact(
                key=key,
                value=note,
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.INFERRED,
                confidence=Confidence.MEDIUM,
                source=SourceExcerpt(section=section, text=source_text[:2_000]),
                user_note=f"Reference learning · {scope} · pending explicit review",
                source_reference_ids=[reference.id],
            )
        )
    return proposals


def _merge_reference_learning_proposals(
    profile: CandidateProfile,
    proposals: list[ProfileFact],
) -> list[UUID]:
    """Merge pending suggestions without losing many-to-one reference provenance."""

    queued = set(profile.reference_learning_fact_ids)
    queued_ids: list[UUID] = []
    changed = False
    for proposal in proposals:
        signature = profile_fact_signature(proposal)
        existing = next(
            (fact for fact in reversed(profile.facts) if profile_fact_signature(fact) == signature),
            None,
        )
        if existing is None:
            profile.facts.append(proposal)
            queued.add(proposal.id)
            queued_ids.append(proposal.id)
            changed = True
            continue
        is_reference_pending = existing.needs_confirmation and (
            existing.id in queued
            or bool(existing.source_reference_ids)
            or (existing.user_note or "").startswith("reference-learning:")
        )
        if not is_reference_pending:
            # Respect an earlier user decision, and never take ownership of an
            # unrelated pending Compass fact with the same wording.
            continue
        merged_sources = list(
            dict.fromkeys([*existing.source_reference_ids, *proposal.source_reference_ids])
        )
        if merged_sources != existing.source_reference_ids:
            existing.source_reference_ids = merged_sources
            changed = True
        queued.add(existing.id)
        queued_ids.append(existing.id)
    profile.reference_learning_fact_ids = [
        *(fact_id for fact_id in profile.reference_learning_fact_ids if fact_id in queued),
        *(fact_id for fact_id in queued_ids if fact_id not in profile.reference_learning_fact_ids),
    ]
    if changed:
        profile.updated_at = datetime.now(timezone.utc)
    return list(dict.fromkeys(queued_ids))


def _remove_pending_reference_learning(
    profile: CandidateProfile,
    reference_id: UUID,
) -> None:
    prefix = f"reference-learning:{reference_id}:"
    queued = set(profile.reference_learning_fact_ids)
    remove_ids: set[UUID] = set()
    changed = False
    for fact in profile.facts:
        if not fact.needs_confirmation or fact.id not in queued:
            continue
        if reference_id in fact.source_reference_ids:
            fact.source_reference_ids = [
                source_id for source_id in fact.source_reference_ids if source_id != reference_id
            ]
            changed = True
            if not fact.source_reference_ids:
                remove_ids.add(fact.id)
        elif not fact.source_reference_ids and (fact.user_note or "").startswith(prefix):
            # Compatibility with the pre-v0.7.1c string-encoded provenance.
            remove_ids.add(fact.id)
            changed = True
    if not changed:
        return
    profile.facts = [fact for fact in profile.facts if fact.id not in remove_ids]
    profile.reference_learning_fact_ids = [
        fact_id for fact_id in profile.reference_learning_fact_ids if fact_id not in remove_ids
    ]
    profile.updated_at = datetime.now(timezone.utc)


def pending_reference_learning_ids(profile: CandidateProfile) -> list[UUID]:
    pending = {fact.id for fact in profile.pending_facts}
    return [fact_id for fact_id in profile.reference_learning_fact_ids if fact_id in pending]


def _reject_prohibited_input(text: str) -> None:
    categories = detect_prohibited_categories(text)
    if not categories:
        return
    raise ProfileWorkflowError(
        "Processing stopped locally because the text appears to contain prohibited "
        f"data: {', '.join(categories)}. Remove that information and try again."
    )


def _validate_reference_learning_request(
    *,
    positives: list[str],
    learning_enabled: bool,
    learning_scope: list[str],
    job: JobPosting | None,
) -> None:
    """Validate new learning actions without making legacy ReferenceJob rows unreadable."""

    if not learning_enabled:
        return
    if not any(item.strip() for item in positives):
        raise ProfileWorkflowError(
            "Reference learning requires at least one positive note. Negative notes stay "
            "reference-only and cannot create Compass suggestions."
        )
    if not learning_scope:
        raise ProfileWorkflowError("Choose at least one area for reference learning.")
    if job is None:
        raise ProfileWorkflowError(
            "Reference learning requires structured evidence from the verified job."
        )


def _supersede_previous_mobility_limits(
    profile: CandidateProfile,
    new_fact_ids: list[UUID],
) -> None:
    """Keep the latest explicit origin and limit active in every projection."""

    selected_ids = set(new_fact_ids)
    current_facts = [fact for fact in profile.facts if fact.id in selected_ids]
    origin_keys = {"location.origin", "commute.origin", "mobility.origin"}
    mobility_touched = False
    for current in current_facts:
        is_origin = current.key in origin_keys
        is_limit = current.key.startswith("commute.") and current.key.endswith(".max_minutes")
        if not is_origin and not is_limit:
            continue
        mobility_touched = True
        for previous in profile.facts:
            if previous.id == current.id or previous.evidence_status != EvidenceStatus.CONFIRMED:
                continue
            if is_origin and previous.key not in origin_keys:
                continue
            if is_limit and previous.key != current.key:
                continue
            apply_review(profile, previous.id, ReviewAction.REJECT)
            previous.user_note = "Superseded by a later Compass answer"
    if mobility_touched:
        sync_location_projection_from_facts(profile)


def _sync_mobility_if_touched(profile: CandidateProfile, fact_ids: list[UUID]) -> None:
    selected = set(fact_ids)
    touched = any(
        fact.id in selected
        and (
            fact.source.section == ProfileSection.LOCATION_MOBILITY
            or fact.key in {"location.origin", "commute.origin", "mobility.origin"}
            or (fact.key.startswith("commute.") and fact.key.endswith(".max_minutes"))
        )
        for fact in profile.facts
    )
    if touched:
        sync_location_projection_from_facts(profile)


_DIRECT_STATEMENT_LEVELS = {
    ProfileSection.MUST_HAVES: RequirementLevel.MUST_HAVE,
    ProfileSection.EXCLUSIONS: RequirementLevel.EXCLUSION,
    ProfileSection.DIRECTION: RequirementLevel.PREFERENCE,
    ProfileSection.PREFERENCES: RequirementLevel.PREFERENCE,
    ProfileSection.ENVIRONMENT_CULTURE: RequirementLevel.PREFERENCE,
}


def _direct_statement_fact(section: ProfileSection, text: str) -> ProfileFact:
    """Retain explicit user intent when structured extraction returns no fact."""

    return ProfileFact(
        key=f"user.{section.value}.statement",
        value=text[:1_000],
        level=_DIRECT_STATEMENT_LEVELS.get(section, RequirementLevel.OPEN),
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=text[:2_000]),
        user_note="Saved directly from an explicit Compass addition",
        needs_confirmation=False,
    )


class ProfileWorkflowService:
    def __init__(
        self,
        repository: ProfileWorkspaceRepository,
        *,
        extractor: ProfileExtractorPort | None = None,
        extractor_setup_error: Exception | None = None,
        fetcher: PublicUrlFetcher | None = None,
        account_id: UUID | None = None,
        persona_id: UUID | None = None,
    ) -> None:
        self.repository = repository
        self.extractor = extractor
        self.extractor_setup_error = extractor_setup_error
        self.fetcher = fetcher
        self.account_id = account_id
        self.persona_id = persona_id
        self.last_extraction_warning: str | None = None

    def _checkpoint_compass_input(
        self,
        workspace: ProfileWorkspace,
        section: ProfileSection,
        *,
        submitted_text: str,
        raw_section_text: str,
    ) -> ProfileWorkspace:
        """Durably save user input before any optional provider call begins."""

        try:
            self.repository.add_message(
                workspace.id,
                ConversationRole.USER,
                submitted_text,
                section=section,
            )
            now = datetime.now(timezone.utc)
            workspace.session.profile.raw_sections[section] = raw_section_text.strip()
            workspace.session.profile.updated_at = now
            workspace.session.updated_at = now
            return self.repository.save(workspace)
        except Exception as exc:
            raise ProfileWorkflowError(
                "The Compass could not finish its local save, so no AI request was made. "
                "Check local database access and free disk space, then retry. The conversation "
                "log may already contain the submitted text."
            ) from exc

    def _extract_section(
        self,
        section: ProfileSection,
        text: str,
    ) -> tuple[SectionExtraction | None, str | None]:
        if self.extractor is None:
            return None, safe_profile_extraction_diagnostic(self.extractor_setup_error)
        try:
            return self.extractor.extract(section, text), None
        except Exception as exc:
            return None, safe_profile_extraction_diagnostic(exc)

    def _save_processed_workspace(
        self,
        workspace: ProfileWorkspace,
    ) -> ProfileWorkspace:
        try:
            return self.repository.save(workspace)
        except Exception as exc:
            raise ProfileWorkflowError(
                "Your original input is saved locally, but the Compass could not save the "
                "interpreted update. Check local database access and free disk space, then retry."
            ) from exc

    def _save_direct_extraction_fallback(
        self,
        workspace: ProfileWorkspace,
        section: ProfileSection,
        *,
        raw_section_text: str,
        submitted_text: str,
        diagnostic: str,
        clarification: bool = False,
        old_question: str | None = None,
    ) -> ProfileWorkspace:
        warning = (
            "Your input was saved locally as an editable Compass statement, but AI structuring "
            f"was unavailable. {diagnostic}"
        )
        self.last_extraction_warning = warning
        extraction = SectionExtraction(
            summary=warning,
            facts=[],
            follow_up_question=None,
        )
        merge = record_section_extraction(
            workspace.session,
            section,
            raw_section_text,
            extraction,
            explicit_fact_text=submitted_text,
        )
        merged_fact_ids = [*merge.added_fact_ids, *merge.refreshed_pending_fact_ids]
        if not merged_fact_ids:
            fallback = _direct_statement_fact(section, submitted_text)
            signature = profile_fact_signature(fallback)
            if not any(
                profile_fact_signature(fact) == signature
                and fact.evidence_status == EvidenceStatus.CONFIRMED
                for fact in workspace.session.profile.facts
            ):
                workspace.session.profile.facts.append(fallback)
                merged_fact_ids.append(fallback.id)
        progress = progress_for(workspace.session, section)
        if clarification:
            progress.clarification_answer = submitted_text
        if old_question in workspace.session.profile.unresolved_questions:
            workspace.session.profile.unresolved_questions.remove(old_question)
        accept_user_input_facts(workspace.session.profile, merged_fact_ids)
        _sync_compensation_from_fact_ids(workspace.session.profile, merged_fact_ids)
        _supersede_previous_mobility_limits(workspace.session.profile, merged_fact_ids)
        complete_section_review(workspace.session, section)
        saved = self._save_processed_workspace(workspace)
        try:
            self.repository.add_message(
                saved.id,
                ConversationRole.ASSISTANT,
                warning,
                section=section,
            )
        except Exception:
            # The Compass checkpoint and direct statement are already durable.
            # The request-level flash still communicates the provider failure.
            pass
        return saved

    def start(self) -> ProfileWorkspace:
        workspace = self.repository.create(
            account_id=self.account_id,
            persona_id=self.persona_id,
        )
        self._ask_current_question(workspace)
        return workspace

    def answer(self, workspace_id: UUID, answer: str) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        if next_review_section(workspace.session) is not None or pending_reference_learning_ids(
            workspace.session.profile
        ):
            raise ProfileWorkflowError(
                "Review the pending CV or learned evidence before continuing."
            )
        clarification_section = next_clarification_section(workspace.session)
        section = clarification_section or next_pending_section(workspace.session)
        if section is None:
            raise ProfileWorkflowError("The guided profile has no unanswered section.")

        clean_answer = answer.strip()
        if not clean_answer:
            raise ProfileWorkflowError("Write a short answer before continuing.")
        _reject_prohibited_input(clean_answer)
        progress = progress_for(workspace.session, section)
        if clarification_section:
            original_answer = workspace.session.profile.raw_sections.get(section, "")
            extraction_input = (
                f"{original_answer}\n\nClarification from the user: {clean_answer}".strip()
            )
            old_question = progress.follow_up_question
        else:
            extraction_input = clean_answer
            old_question = None
        workspace = self._checkpoint_compass_input(
            workspace,
            section,
            submitted_text=clean_answer,
            raw_section_text=extraction_input,
        )
        extraction, diagnostic = self._extract_section(section, extraction_input)
        if extraction is None:
            saved = self._save_direct_extraction_fallback(
                workspace,
                section,
                raw_section_text=extraction_input,
                submitted_text=clean_answer,
                diagnostic=diagnostic or safe_profile_extraction_diagnostic(None),
                clarification=clarification_section is not None,
                old_question=old_question,
            )
            self._ask_current_question(saved)
            return saved
        merge = record_section_extraction(
            workspace.session,
            section,
            extraction_input,
            extraction,
            unresolved_follow_up=(
                bool(extraction.follow_up_question) and clarification_section is None
            ),
        )
        progress = progress_for(workspace.session, section)
        if clarification_section:
            progress.clarification_answer = clean_answer
            progress.follow_up_question = None
            if old_question in workspace.session.profile.unresolved_questions:
                workspace.session.profile.unresolved_questions.remove(old_question)
        accept_user_input_facts(
            workspace.session.profile,
            [*merge.added_fact_ids, *merge.refreshed_pending_fact_ids],
        )
        _sync_compensation_from_fact_ids(
            workspace.session.profile,
            [*merge.added_fact_ids, *merge.refreshed_pending_fact_ids],
        )
        _supersede_previous_mobility_limits(
            workspace.session.profile,
            [*merge.added_fact_ids, *merge.refreshed_pending_fact_ids],
        )
        complete_section_review(workspace.session, section)
        response = extraction.summary
        if extraction.follow_up_question and clarification_section is None:
            response += f"\n\nOne point to clarify: {extraction.follow_up_question}"
        saved = self._save_processed_workspace(workspace)
        self.repository.add_message(
            saved.id,
            ConversationRole.ASSISTANT,
            response,
            section=section,
        )
        self._ask_current_question(saved)
        return saved

    def review_fact(
        self,
        workspace_id: UUID,
        fact_id: UUID,
        action: ReviewAction,
        *,
        new_value: str | None = None,
        new_level: RequirementLevel | None = None,
        continue_guided: bool = True,
    ) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        section = next_review_section(workspace.session)
        if section is None:
            pending_reference_ids = set(pending_reference_learning_ids(workspace.session.profile))
            if fact_id not in pending_reference_ids:
                raise ProfileWorkflowError("There is no pending Review Tray.")
            apply_review(
                workspace.session.profile,
                fact_id,
                action,
                new_value=new_value,
                new_level=new_level,
            )
            if action == ReviewAction.EDIT_VALUE and new_level is not None:
                edited_fact = next(
                    fact for fact in workspace.session.profile.facts if fact.id == fact_id
                )
                if edited_fact.level != new_level:
                    apply_review(
                        workspace.session.profile,
                        fact_id,
                        ReviewAction.CHANGE_LEVEL,
                        new_level=new_level,
                    )
            updated_fact = next(
                item for item in workspace.session.profile.facts if item.id == fact_id
            )
            canonicalize_mobility_fact(updated_fact)
            _sync_compensation_from_fact_ids(workspace.session.profile, [fact_id])
            _sync_mobility_if_touched(workspace.session.profile, [fact_id])
            workspace.session.profile.reference_learning_fact_ids = [
                queued_id
                for queued_id in workspace.session.profile.reference_learning_fact_ids
                if queued_id != fact_id
            ]
            saved = self.repository.save(workspace)
            if not pending_reference_learning_ids(saved.session.profile) and continue_guided:
                self._ask_current_question(saved)
            return saved
        progress = progress_for(workspace.session, section)
        if fact_id not in progress.proposed_fact_ids:
            raise ProfileWorkflowError("This statement is not in the current Review Tray.")
        apply_review(
            workspace.session.profile,
            fact_id,
            action,
            new_value=new_value,
            new_level=new_level,
        )
        if action == ReviewAction.EDIT_VALUE and new_level is not None:
            edited_fact = next(
                fact for fact in workspace.session.profile.facts if fact.id == fact_id
            )
            if edited_fact.level != new_level:
                apply_review(
                    workspace.session.profile,
                    fact_id,
                    ReviewAction.CHANGE_LEVEL,
                    new_level=new_level,
                )
        updated_fact = next(item for item in workspace.session.profile.facts if item.id == fact_id)
        canonicalize_mobility_fact(updated_fact)
        _sync_compensation_from_fact_ids(workspace.session.profile, [fact_id])
        _sync_mobility_if_touched(workspace.session.profile, [fact_id])
        pending_ids = {
            fact.id
            for fact in workspace.session.profile.pending_facts
            if fact.id in progress.proposed_fact_ids
        }
        if not pending_ids:
            complete_section_review(workspace.session, section)
        saved = self.repository.save(workspace)
        if not pending_ids and continue_guided:
            self._ask_current_question(saved)
        return saved

    def confirm_facts(
        self,
        workspace_id: UUID,
        fact_ids: list[UUID],
        *,
        continue_guided: bool = True,
    ) -> ProfileWorkspace:
        """Confirm selected Review Tray statements in one authoritative action."""

        workspace = self._required(workspace_id)
        section = next_review_section(workspace.session)
        if section is None:
            pending_ids = set(pending_reference_learning_ids(workspace.session.profile))
            selected = list(dict.fromkeys(fact_ids))
            if not selected:
                raise ProfileWorkflowError("Select at least one statement to confirm.")
            if set(selected).difference(pending_ids):
                raise ProfileWorkflowError(
                    "One or more selected statements are no longer awaiting review."
                )
            for fact_id in selected:
                apply_review(workspace.session.profile, fact_id, ReviewAction.CONFIRM)
            _sync_compensation_from_fact_ids(workspace.session.profile, selected)
            _sync_mobility_if_touched(workspace.session.profile, selected)
            workspace.session.profile.reference_learning_fact_ids = [
                queued_id
                for queued_id in workspace.session.profile.reference_learning_fact_ids
                if queued_id not in set(selected)
            ]
            saved = self.repository.save(workspace)
            if not pending_reference_learning_ids(saved.session.profile) and continue_guided:
                self._ask_current_question(saved)
            return saved
        selected = list(dict.fromkeys(fact_ids))
        if not selected:
            raise ProfileWorkflowError("Select at least one statement to confirm.")
        progress = progress_for(workspace.session, section)
        pending_ids = {
            fact.id
            for fact in workspace.session.profile.pending_facts
            if fact.id in progress.proposed_fact_ids
        }
        invalid = set(selected).difference(pending_ids)
        if invalid:
            raise ProfileWorkflowError(
                "One or more selected statements are no longer awaiting review."
            )

        # Validate the complete selection before mutating any fact. The repository
        # then persists every user decision in one transaction-like save.
        for fact_id in selected:
            apply_review(
                workspace.session.profile,
                fact_id,
                ReviewAction.CONFIRM,
            )
        _sync_compensation_from_fact_ids(workspace.session.profile, selected)
        _sync_mobility_if_touched(workspace.session.profile, selected)
        remaining_ids = {
            fact.id
            for fact in workspace.session.profile.pending_facts
            if fact.id in progress.proposed_fact_ids
        }
        if not remaining_ids:
            complete_section_review(workspace.session, section)
        saved = self.repository.save(workspace)
        if not remaining_ids and continue_guided:
            self._ask_current_question(saved)
        return saved

    def add_section_detail(
        self,
        workspace_id: UUID,
        section: ProfileSection,
        answer: str,
    ) -> ProfileWorkspace:
        """Extract one targeted addition without restarting the guided loop."""

        workspace = self._required(workspace_id)
        clean_answer = answer.strip()
        if not clean_answer:
            raise ProfileWorkflowError("Write a short addition before saving it.")
        _reject_prohibited_input(clean_answer)
        progress = progress_for(workspace.session, section)
        old_question = progress.follow_up_question
        previous = workspace.session.profile.raw_sections.get(section, "").strip()
        combined = (
            f"{previous}\n\nAdditional user input:\n{clean_answer}" if previous else clean_answer
        )
        workspace = self._checkpoint_compass_input(
            workspace,
            section,
            submitted_text=clean_answer,
            raw_section_text=combined,
        )
        extraction, diagnostic = self._extract_section(section, clean_answer)
        if extraction is None:
            return self._save_direct_extraction_fallback(
                workspace,
                section,
                raw_section_text=combined,
                submitted_text=clean_answer,
                diagnostic=diagnostic or safe_profile_extraction_diagnostic(None),
                old_question=old_question,
            )
        merge = record_section_extraction(
            workspace.session,
            section,
            combined,
            extraction,
            unresolved_follow_up=bool(extraction.follow_up_question),
            explicit_fact_text=clean_answer,
        )
        merged_fact_ids = [*merge.added_fact_ids, *merge.refreshed_pending_fact_ids]
        if not extraction.facts and not merged_fact_ids:
            fallback = _direct_statement_fact(section, clean_answer)
            signature = profile_fact_signature(fallback)
            if not any(
                profile_fact_signature(fact) == signature
                and fact.evidence_status == EvidenceStatus.CONFIRMED
                for fact in workspace.session.profile.facts
            ):
                workspace.session.profile.facts.append(fallback)
                merged_fact_ids.append(fallback.id)
        if old_question in workspace.session.profile.unresolved_questions:
            workspace.session.profile.unresolved_questions.remove(old_question)
        accept_user_input_facts(
            workspace.session.profile,
            merged_fact_ids,
        )
        _sync_compensation_from_fact_ids(workspace.session.profile, merged_fact_ids)
        _supersede_previous_mobility_limits(
            workspace.session.profile,
            merged_fact_ids,
        )
        complete_section_review(workspace.session, section)
        saved = self._save_processed_workspace(workspace)
        self.repository.add_message(
            saved.id,
            ConversationRole.ASSISTANT,
            extraction.summary,
            section=section,
        )
        return saved

    def add_private_evidence(
        self,
        workspace_id: UUID,
        text: str,
        *,
        source_label: str = "uploaded CV",
    ) -> ProfileWorkspace:
        """Extract reviewable experience facts without saving the CV in the conversation."""

        workspace = self._required(workspace_id)
        if next_review_section(workspace.session) is not None or pending_reference_learning_ids(
            workspace.session.profile
        ):
            raise ProfileWorkflowError(
                "Finish the current Review Tray before extracting CV evidence."
            )
        clean_text = text.strip()
        if not clean_text:
            raise ProfileWorkflowError("The CV contains no extractable text.")
        _reject_prohibited_input(clean_text)
        extraction, diagnostic = self._extract_section(ProfileSection.EXPERIENCE, clean_text)
        if extraction is None:
            raise ProfileWorkflowError(
                "CV text was not retained or added to the Compass because AI extraction failed. "
                f"{diagnostic or safe_profile_extraction_diagnostic(None)} Prepare the preview "
                "again after correcting the provider configuration."
            )
        proposals = extraction.to_profile_facts(ProfileSection.EXPERIENCE)
        merge = merge_extracted_facts(workspace.session.profile, proposals)
        proposed_ids = [*merge.added_fact_ids, *merge.refreshed_pending_fact_ids]
        if not proposed_ids:
            raise ProfileWorkflowError(
                "The CV produced no new reviewable evidence; confirmed decisions were protected."
            )
        progress = progress_for(workspace.session, ProfileSection.EXPERIENCE)
        progress.status = SectionStatus.REVIEW_PENDING
        progress.summary = f"Evidence proposed from {source_label}: {extraction.summary}"
        progress.follow_up_question = None
        progress.proposed_fact_ids = proposed_ids
        progress.updated_at = datetime.now(timezone.utc)
        workspace.session.updated_at = progress.updated_at
        # Deliberately do not write clean_text to raw_sections or conversation messages.
        return self._save_processed_workspace(workspace)

    def add_feedback_preference(
        self,
        workspace_id: UUID,
        text: str,
        *,
        source_label: str,
    ) -> ProfileWorkspace:
        """Turn an explicit job decision into one editable Compass preference."""

        workspace = self._required(workspace_id)
        clean_text = " ".join(text.split())
        if not clean_text:
            raise ProfileWorkflowError("Write a short reason before teaching the Compass.")
        proposal = ProfileFact(
            key="feedback.preference",
            value=clean_text[:1_000],
            level=RequirementLevel.PREFERENCE,
            evidence_status=EvidenceStatus.CONFIRMED,
            confidence=Confidence.HIGH,
            source=SourceExcerpt(
                section=ProfileSection.PREFERENCES,
                text=clean_text[:2_000],
            ),
            user_note=f"Explicitly taught from feedback on {source_label}"[:1_000],
            needs_confirmation=False,
        )
        signature = profile_fact_signature(proposal)
        if any(
            profile_fact_signature(fact) == signature
            and fact.evidence_status == EvidenceStatus.CONFIRMED
            for fact in workspace.session.profile.facts
        ):
            return workspace
        workspace.session.profile.facts.append(proposal)
        workspace.session.profile.updated_at = datetime.now(timezone.utc)
        workspace.session.updated_at = workspace.session.profile.updated_at
        return self.repository.save(workspace)

    def revise_confirmed_fact(
        self,
        workspace_id: UUID,
        fact_id: UUID,
        *,
        action: ReviewAction,
        new_value: str | None = None,
        new_level: RequirementLevel | None = None,
    ) -> ProfileWorkspace:
        """Apply a direct Compass correction outside the extraction Review Tray."""

        workspace = self._required(workspace_id)
        fact = next(
            (candidate for candidate in workspace.session.profile.facts if candidate.id == fact_id),
            None,
        )
        if fact is None or fact.evidence_status != EvidenceStatus.CONFIRMED:
            raise ProfileWorkflowError("Only a confirmed Compass statement can be edited here.")
        if action not in {
            ReviewAction.EDIT_VALUE,
            ReviewAction.CHANGE_LEVEL,
            ReviewAction.REJECT,
        }:
            raise ProfileWorkflowError("Unsupported Compass edit.")
        apply_review(
            workspace.session.profile,
            fact_id,
            action,
            new_value=new_value,
            new_level=new_level,
        )
        if action == ReviewAction.EDIT_VALUE and new_level is not None:
            updated_fact = next(
                item for item in workspace.session.profile.facts if item.id == fact_id
            )
            if updated_fact.level != new_level:
                apply_review(
                    workspace.session.profile,
                    fact_id,
                    ReviewAction.CHANGE_LEVEL,
                    new_level=new_level,
                )
        updated_fact = next(item for item in workspace.session.profile.facts if item.id == fact_id)
        canonicalize_mobility_fact(updated_fact)
        _sync_compensation_from_fact_ids(workspace.session.profile, [fact_id])
        _sync_mobility_if_touched(workspace.session.profile, [fact_id])
        return self.repository.save(workspace)

    def save_compensation_range(
        self,
        workspace_id: UUID,
        *,
        minimum_gross_annual: int,
        target_gross_annual: int | None,
        currency: CompensationCurrency | None = None,
    ) -> ProfileWorkspace:
        """Atomically replace the active annual-gross criteria from the Compass tile."""

        workspace = self._required(workspace_id)
        profile = workspace.session.profile
        set_compensation_range(
            profile,
            minimum_gross_annual,
            target_gross_annual,
            currency,
        )
        selected_currency = profile.compensation.currency

        previous_amount_facts = [
            fact
            for fact in profile.facts
            if fact.evidence_status == EvidenceStatus.CONFIRMED
            and _compensation_values_from_fact(fact) != (None, None)
        ]
        for fact in previous_amount_facts:
            apply_review(profile, fact.id, ReviewAction.REJECT)

        now = datetime.now(timezone.utc)
        new_facts: list[ProfileFact] = []
        if minimum_gross_annual > 0:
            new_facts.append(
                ProfileFact(
                    created_at=now,
                    key="compensation.annual_gross",
                    value=f"{selected_currency} {minimum_gross_annual}",
                    level=RequirementLevel.MUST_HAVE,
                    evidence_status=EvidenceStatus.CONFIRMED,
                    confidence=Confidence.HIGH,
                    source=SourceExcerpt(
                        section=ProfileSection.COMPENSATION_TIME,
                        text=(
                            "Annual gross salary minimum selected in Compass: "
                            f"{selected_currency} {minimum_gross_annual:,}."
                        ),
                    ),
                    user_note="Set with the Compass annual-gross range editor",
                    reviewed_at=now,
                    needs_confirmation=False,
                )
            )
        if target_gross_annual is not None and target_gross_annual != minimum_gross_annual:
            new_facts.append(
                ProfileFact(
                    created_at=now,
                    key="compensation.annual_gross",
                    value=f"{selected_currency} {target_gross_annual}",
                    level=RequirementLevel.PREFERENCE,
                    evidence_status=EvidenceStatus.CONFIRMED,
                    confidence=Confidence.HIGH,
                    source=SourceExcerpt(
                        section=ProfileSection.COMPENSATION_TIME,
                        text=(
                            "Annual gross salary target selected in Compass: "
                            f"{selected_currency} {target_gross_annual:,}."
                        ),
                    ),
                    user_note="Set with the Compass annual-gross range editor",
                    reviewed_at=now,
                    needs_confirmation=False,
                )
            )
        profile.facts.extend(new_facts)
        profile.updated_at = now
        workspace.session.updated_at = now
        return self.repository.save(workspace)

    def save_candidate_languages(
        self,
        workspace_id: UUID,
        *,
        names: list[str],
        proficiencies: list[str],
        programming: bool,
    ) -> ProfileWorkspace:
        """Replace one language-catalog projection as confirmed Experience evidence.

        Profile facts already live inside the persona-owned session JSON, so this
        editor needs no database column or risky migration.  Only facts created by
        the same editor are replaced; reviewed CV and free-text evidence remain
        authoritative and untouched.
        """

        if len(names) != len(proficiencies):
            raise ProfileWorkflowError("Every selected language needs one proficiency level.")
        if len(names) > 100:
            raise ProfileWorkflowError("Select at most 100 languages in one catalog.")

        selections: dict[str, PracticalProficiency] = {}
        for submitted_name, submitted_level in zip(names, proficiencies, strict=True):
            canonical_name = canonical_catalog_name(submitted_name, programming=programming)
            if canonical_name is None:
                raise ProfileWorkflowError("Choose languages from the maintained catalog.")
            try:
                proficiency = PracticalProficiency(submitted_level)
            except ValueError as exc:
                raise ProfileWorkflowError(
                    "Choose beginner, intermediate, professional, or native proficiency."
                ) from exc
            selections[canonical_name] = proficiency

        workspace = self._required(workspace_id)
        profile = workspace.session.profile
        fact_key = PROGRAMMING_LANGUAGE_FACT_KEY if programming else SPOKEN_LANGUAGE_FACT_KEY
        catalog_mentions = (
            mentioned_programming_languages if programming else mentioned_spoken_languages
        )
        for fact in profile.facts:
            if (
                fact.evidence_status == EvidenceStatus.CONFIRMED
                and fact.source.section == ProfileSection.EXPERIENCE
                and (
                    fact.key == fact_key
                    or (
                        is_language_editor_fact(fact)
                        and catalog_mentions(f"{fact.value} {fact.source.text}")
                    )
                )
            ):
                apply_review(profile, fact.id, ReviewAction.REJECT)

        now = datetime.now(timezone.utc)
        kind_label = "Programming language" if programming else "Spoken language"
        for name, proficiency in selections.items():
            profile.facts.append(
                ProfileFact(
                    created_at=now,
                    key=fact_key,
                    value=language_fact_value(name, proficiency),
                    level=RequirementLevel.OPEN,
                    evidence_status=EvidenceStatus.CONFIRMED,
                    confidence=Confidence.HIGH,
                    source=SourceExcerpt(
                        section=ProfileSection.EXPERIENCE,
                        text=(f"{kind_label} selected in Compass: {name} ({proficiency.value})."),
                    ),
                    user_note=(
                        f"{LANGUAGE_EDITOR_NOTE_PREFIX} · "
                        f"{'programming' if programming else 'spoken'}"
                    ),
                    reviewed_at=now,
                    needs_confirmation=False,
                )
            )

        experience_progress = progress_for(workspace.session, ProfileSection.EXPERIENCE)
        has_experience_evidence = any(
            fact.evidence_status == EvidenceStatus.CONFIRMED
            and fact.source.section == ProfileSection.EXPERIENCE
            for fact in profile.facts
        )
        if has_experience_evidence and experience_progress.status in {
            SectionStatus.PENDING,
            SectionStatus.SKIPPED,
        }:
            experience_progress.status = SectionStatus.COMPLETED
            experience_progress.summary = _LANGUAGE_EDITOR_PROGRESS_SUMMARY
            experience_progress.updated_at = now
        elif (
            not has_experience_evidence
            and experience_progress.status == SectionStatus.COMPLETED
            and experience_progress.summary == _LANGUAGE_EDITOR_PROGRESS_SUMMARY
        ):
            experience_progress.status = SectionStatus.PENDING
            experience_progress.summary = None
            experience_progress.updated_at = now
            workspace.session.completed_at = None

        profile.updated_at = now
        workspace.session.updated_at = now
        return self.repository.save(workspace)

    def save_mobility_preferences(
        self,
        workspace_id: UUID,
        *,
        origin_label: str,
        car_minutes: int,
        transit_minutes: int,
        bicycle_minutes: int,
    ) -> ProfileWorkspace:
        """Replace the compact public-origin and modal commute preferences atomically."""

        values = {
            TravelMode.CAR: car_minutes,
            TravelMode.TRANSIT: transit_minutes,
            TravelMode.BICYCLE: bicycle_minutes,
        }
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
            raise ProfileWorkflowError("Commute limits must be whole minutes.")
        if any(value < 0 or value > 360 for value in values.values()):
            raise ProfileWorkflowError("Commute limits must be between 0 and 360 minutes.")

        clean_origin = " ".join(origin_label.split())[:200]
        if any(values.values()) and not clean_origin:
            raise ProfileWorkflowError(
                "Choose a nearby public starting point before setting commute limits."
            )

        workspace = self._required(workspace_id)
        profile = workspace.session.profile
        origin_keys = {"location.origin", "commute.origin", "mobility.origin"}
        previous_levels: dict[TravelMode, RequirementLevel] = {}
        for fact in sorted(profile.confirmed_facts, key=lambda item: item.created_at):
            limit = mobility_limit_from_fact(fact)
            if limit is not None and limit[0] in values:
                previous_levels[limit[0]] = fact.level
        if profile.location is not None:
            for constraint in profile.location.travel_constraints:
                if constraint.mode in values and constraint.mode not in previous_levels:
                    previous_levels[constraint.mode] = constraint.level

        replaced = [
            fact
            for fact in profile.facts
            if fact.evidence_status == EvidenceStatus.CONFIRMED
            and (
                fact.key in origin_keys
                or (
                    (limit := mobility_limit_from_fact(fact)) is not None
                    and (not clean_origin or limit[0] in values)
                )
            )
        ]
        for fact in replaced:
            apply_review(profile, fact.id, ReviewAction.REJECT)

        now = datetime.now(timezone.utc)
        selected_constraints = [
            TravelConstraint(
                mode=mode,
                maximum_minutes_one_way=minutes,
                level=previous_levels.get(mode, RequirementLevel.PREFERENCE),
            )
            for mode, minutes in values.items()
            if minutes > 0
        ]
        previous_location = profile.location
        untouched_constraints = (
            [
                constraint
                for constraint in previous_location.travel_constraints
                if constraint.mode not in values
            ]
            if previous_location is not None and clean_origin
            else []
        )
        constraints = [*untouched_constraints, *selected_constraints]
        profile.location = (
            LocationPreference(
                origin_label=clean_origin,
                origin_precision=origin_precision_from_label(clean_origin),
                acceptable_destinations=(
                    list(previous_location.acceptable_destinations)
                    if previous_location is not None
                    else []
                ),
                travel_constraints=constraints,
                relocation=(
                    previous_location.relocation
                    if previous_location is not None
                    else RequirementLevel.OPEN
                ),
                second_residence_allowed=(
                    previous_location.second_residence_allowed
                    if previous_location is not None
                    else None
                ),
            )
            if clean_origin
            else None
        )

        if clean_origin:
            profile.facts.append(
                ProfileFact(
                    created_at=now,
                    key="location.origin",
                    value=clean_origin,
                    level=RequirementLevel.OPEN,
                    evidence_status=EvidenceStatus.CONFIRMED,
                    confidence=Confidence.HIGH,
                    source=SourceExcerpt(
                        section=ProfileSection.LOCATION_MOBILITY,
                        text=f"Nearby public starting point selected in Compass: {clean_origin}.",
                    ),
                    user_note="Set with the Compass location and mobility editor",
                    reviewed_at=now,
                    needs_confirmation=False,
                )
            )
        for constraint in selected_constraints:
            profile.facts.append(
                ProfileFact(
                    created_at=now,
                    key=f"commute.{constraint.mode.value}.max_minutes",
                    value=(
                        f"{constraint.maximum_minutes_one_way} minutes by "
                        f"{mobility_mode_label(constraint.mode)} one way"
                    ),
                    level=constraint.level,
                    evidence_status=EvidenceStatus.CONFIRMED,
                    confidence=Confidence.HIGH,
                    source=SourceExcerpt(
                        section=ProfileSection.LOCATION_MOBILITY,
                        text=(
                            f"Maximum {mobility_mode_label(constraint.mode)} commute selected "
                            "in Compass: "
                            f"{constraint.maximum_minutes_one_way} minutes one way."
                        ),
                    ),
                    user_note="Set with the Compass location and mobility editor",
                    reviewed_at=now,
                    needs_confirmation=False,
                )
            )

        profile.updated_at = now
        workspace.session.updated_at = now
        return self.repository.save(workspace)

    def skip(self, workspace_id: UUID) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        if next_review_section(workspace.session) is not None or pending_reference_learning_ids(
            workspace.session.profile
        ):
            raise ProfileWorkflowError(
                "Review the pending CV or learned evidence before continuing."
            )
        clarification_section = next_clarification_section(workspace.session)
        if clarification_section is not None:
            leave_clarification_open(workspace.session, clarification_section)
            saved = self.repository.save(workspace)
            self._ask_current_question(saved)
            return saved
        section = next_pending_section(workspace.session)
        if section is None:
            raise ProfileWorkflowError("There is no section to skip.")
        mark_section_skipped(workspace.session, section)
        saved = self.repository.save(workspace)
        self._ask_current_question(saved)
        return saved

    def revisit_skipped(self, workspace_id: UUID) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        if next_review_section(workspace.session) is not None or pending_reference_learning_ids(
            workspace.session.profile
        ):
            raise ProfileWorkflowError("Finish the current Review Tray first.")
        reopened = reopen_skipped_sections(workspace.session)
        if not reopened:
            raise ProfileWorkflowError("There are no skipped sections to revisit.")
        saved = self.repository.save(workspace)
        self.repository.add_message(
            saved.id,
            ConversationRole.ASSISTANT,
            "Let’s return to the questions you left open.",
        )
        self._ask_current_question(saved)
        return saved

    def add_reference(
        self,
        workspace_id: UUID,
        url: str,
        *,
        positives: list[str],
        negatives: list[str],
        learning_enabled: bool,
        learning_scope: list[str],
    ) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        _reject_prohibited_input("\n".join([*positives, *negatives]))
        _validate_reference_learning_request(
            positives=positives,
            learning_enabled=learning_enabled,
            learning_scope=learning_scope,
            job=None,
        )
        validated_url = str(TypeAdapter(AnyHttpUrl).validate_python(url.strip()))
        fetcher = self.fetcher or PublicUrlFetcher()
        document = fetcher.fetch(validated_url)
        reference = ReferenceJob(
            url=document.requested_url,
            resolved_url=document.final_url,
            url_http_status=document.status_code,
            url_verified_at=document.fetched_at,
            positives=positives,
            negatives=negatives,
            learning_enabled=learning_enabled,
            learning_scope=learning_scope if learning_enabled else [],
        )
        workspace.session.profile.reference_jobs.append(reference)
        return self.repository.save(workspace)

    def upsert_verified_reference(
        self,
        workspace_id: UUID,
        *,
        requested_url: str,
        resolved_url: str,
        http_status: int,
        verified_at: datetime,
        positives: list[str],
        negatives: list[str],
        learning_enabled: bool,
        learning_scope: list[str],
        job: JobPosting | None = None,
    ) -> ProfileWorkspace:
        """Store the preferences for a URL already verified by job ingestion."""

        workspace = self._required(workspace_id)
        _reject_prohibited_input("\n".join([*positives, *negatives]))
        _validate_reference_learning_request(
            positives=positives,
            learning_enabled=learning_enabled,
            learning_scope=learning_scope,
            job=job,
        )
        requested = str(TypeAdapter(AnyHttpUrl).validate_python(requested_url.strip()))
        resolved = str(TypeAdapter(AnyHttpUrl).validate_python(resolved_url.strip()))
        identities = {normalize_job_url(requested), normalize_job_url(resolved)}
        existing = next(
            (
                reference
                for reference in workspace.session.profile.reference_jobs
                if identities.intersection(self._reference_identities(reference))
            ),
            None,
        )
        payload = {
            "url": requested,
            "resolved_url": resolved,
            "url_http_status": http_status,
            "url_verified_at": verified_at,
            "positives": positives,
            "negatives": negatives,
            "learning_enabled": learning_enabled,
            "learning_scope": learning_scope if learning_enabled else [],
        }
        if existing is None:
            reference = ReferenceJob(**payload)
            workspace.session.profile.reference_jobs.append(reference)
        else:
            _remove_pending_reference_learning(workspace.session.profile, existing.id)
            replacement = ReferenceJob(id=existing.id, **payload)
            workspace.session.profile.reference_jobs = [
                replacement if reference.id == existing.id else reference
                for reference in workspace.session.profile.reference_jobs
            ]
            reference = replacement
        if reference.learning_enabled and job is not None:
            _merge_reference_learning_proposals(
                workspace.session.profile,
                _reference_learning_proposals(reference, job),
            )
        return self.repository.save(workspace)

    def upsert_manual_reference(
        self,
        workspace_id: UUID,
        *,
        identity_url: str,
        positives: list[str],
        negatives: list[str],
        learning_enabled: bool,
        learning_scope: list[str],
        job: JobPosting,
    ) -> ProfileWorkspace:
        """Store settings for pasted text without asserting that its link was checked."""

        workspace = self._required(workspace_id)
        _reject_prohibited_input("\n".join([*positives, *negatives]))
        _validate_reference_learning_request(
            positives=positives,
            learning_enabled=learning_enabled,
            learning_scope=learning_scope,
            job=job,
        )
        identity = str(TypeAdapter(AnyHttpUrl).validate_python(identity_url.strip()))
        normalized_identity = normalize_job_url(identity)
        existing = next(
            (
                reference
                for reference in workspace.session.profile.reference_jobs
                if normalized_identity in self._reference_identities(reference)
            ),
            None,
        )
        payload = {
            "url": identity,
            "input_method": "manual_text",
            "positives": positives,
            "negatives": negatives,
            "learning_enabled": learning_enabled,
            "learning_scope": learning_scope if learning_enabled else [],
        }
        if existing is None:
            reference = ReferenceJob(**payload)
            workspace.session.profile.reference_jobs.append(reference)
        else:
            _remove_pending_reference_learning(workspace.session.profile, existing.id)
            replacement = ReferenceJob(id=existing.id, **payload)
            workspace.session.profile.reference_jobs = [
                replacement if reference.id == existing.id else reference
                for reference in workspace.session.profile.reference_jobs
            ]
            reference = replacement
        if reference.learning_enabled:
            _merge_reference_learning_proposals(
                workspace.session.profile,
                _reference_learning_proposals(reference, job),
            )
        return self.repository.save(workspace)

    def delete_references_for_urls(
        self,
        workspace_id: UUID,
        urls: list[str],
    ) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        identities = {normalize_job_url(url) for url in urls if url}
        removed = [
            reference
            for reference in workspace.session.profile.reference_jobs
            if identities.intersection(self._reference_identities(reference))
        ]
        for reference in removed:
            _remove_pending_reference_learning(workspace.session.profile, reference.id)
        workspace.session.profile.reference_jobs = [
            reference
            for reference in workspace.session.profile.reference_jobs
            if not identities.intersection(self._reference_identities(reference))
        ]
        return self.repository.save(workspace)

    def delete_reference(self, workspace_id: UUID, reference_id: UUID) -> ProfileWorkspace:
        workspace = self._required(workspace_id)
        previous_count = len(workspace.session.profile.reference_jobs)
        workspace.session.profile.reference_jobs = [
            reference
            for reference in workspace.session.profile.reference_jobs
            if reference.id != reference_id
        ]
        if len(workspace.session.profile.reference_jobs) == previous_count:
            raise ProfileWorkflowError("Reference job not found.")
        _remove_pending_reference_learning(workspace.session.profile, reference_id)
        return self.repository.save(workspace)

    def _ask_current_question(self, workspace: ProfileWorkspace) -> None:
        clarification_section = next_clarification_section(workspace.session)
        if clarification_section is not None:
            progress = progress_for(workspace.session, clarification_section)
            self.repository.add_message(
                workspace.id,
                ConversationRole.ASSISTANT,
                progress.follow_up_question or "Could you clarify that point?",
                section=clarification_section,
            )
            return
        section = next_pending_section(workspace.session)
        if section is None:
            return
        self.repository.add_message(
            workspace.id,
            ConversationRole.ASSISTANT,
            definition_for(section).question,
            section=section,
        )

    @staticmethod
    def _reference_identities(reference: ReferenceJob) -> set[str]:
        return {
            normalize_job_url(str(url))
            for url in (reference.url, reference.resolved_url)
            if url is not None
        }

    def _required(self, workspace_id: UUID) -> ProfileWorkspace:
        workspace = self.repository.get(
            workspace_id,
            account_id=self.account_id,
            persona_id=self.persona_id,
        )
        if workspace is None:
            raise ProfileWorkflowError("Profile workspace not found.")
        return workspace


def workspace_stage(workspace: ProfileWorkspace) -> str:
    if next_review_section(workspace.session) is not None or pending_reference_learning_ids(
        workspace.session.profile
    ):
        return "review"
    if workspace.session.state == SessionState.COMPLETED:
        return "complete"
    return "conversation"
