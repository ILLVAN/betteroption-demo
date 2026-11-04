"""Automatic, content-minimising retention for the private alpha."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from threading import Event

from sqlalchemy import delete, or_, select

from .applications import ApplicationDraftRow
from .accounts import (
    AccountInvitationRow,
    AuthAttemptRow,
    AuthSessionRow,
    PasswordResetRow,
)
from .cv import CvDocumentRow
from .database import Database
from .feedback import ProductFeedbackRow
from .operations import ProviderOperationRow
from .profile import EvidenceStatus
from .profile_repository import ConversationMessageRow, ProfileWorkspaceRow
from .session import ProfileSession
from .settings import Settings
from .telemetry import ModelInvocationRow

REDACTED_SOURCE_TEXT = "Source text deleted by retention policy."


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RetentionPolicy:
    token_record_days: int = 7
    auth_attempt_days: int = 7
    raw_compass_days: int = 30
    pending_fact_days: int = 30
    rejected_fact_days: int = 7
    legacy_cv_hours: int = 24
    provider_telemetry_days: int = 90
    application_draft_days: int = 180
    product_feedback_days: int = 180

    @classmethod
    def from_settings(cls, settings: Settings) -> RetentionPolicy:
        return cls(
            token_record_days=settings.retention_token_record_days,
            auth_attempt_days=settings.retention_auth_attempt_days,
            raw_compass_days=settings.retention_raw_compass_days,
            pending_fact_days=settings.retention_pending_fact_days,
            rejected_fact_days=settings.retention_rejected_fact_days,
            legacy_cv_hours=settings.retention_legacy_cv_hours,
            provider_telemetry_days=settings.retention_provider_telemetry_days,
            application_draft_days=settings.retention_application_draft_days,
            product_feedback_days=settings.retention_product_feedback_days,
        )


@dataclass
class RetentionReport:
    expired_sessions: int = 0
    invitation_records: int = 0
    recovery_records: int = 0
    auth_attempts: int = 0
    conversation_messages: int = 0
    legacy_cv_documents: int = 0
    model_invocations: int = 0
    provider_operations: int = 0
    application_drafts: int = 0
    product_feedback: int = 0
    profile_workspaces_sanitized: int = 0
    raw_compass_sections: int = 0
    pending_facts: int = 0
    rejected_facts: int = 0
    review_events: int = 0
    source_excerpts: int = 0

    @property
    def total_changes(self) -> int:
        return sum(asdict(self).values())


def _deleted_rows(result) -> int:
    return max(0, int(result.rowcount or 0))


def _minimise_profile(
    profile_session: ProfileSession,
    *,
    now: datetime,
    policy: RetentionPolicy,
    report: RetentionReport,
) -> bool:
    profile = profile_session.profile
    raw_cutoff = now - timedelta(days=policy.raw_compass_days)
    pending_cutoff = now - timedelta(days=policy.pending_fact_days)
    rejected_cutoff = now - timedelta(days=policy.rejected_fact_days)
    changed = False

    progress_by_section = {item.section: item for item in profile_session.sections}
    for section in list(profile.raw_sections):
        progress = progress_by_section.get(section)
        if progress is not None and _utc(progress.updated_at) <= raw_cutoff:
            del profile.raw_sections[section]
            report.raw_compass_sections += 1
            changed = True

    retained_facts = []
    for fact in profile.facts:
        created_at = _utc(fact.created_at)
        reviewed_at = _utc(fact.reviewed_at) if fact.reviewed_at else created_at
        if fact.evidence_status == EvidenceStatus.REJECTED and reviewed_at <= rejected_cutoff:
            report.rejected_facts += 1
            changed = True
            continue
        if fact.needs_confirmation and created_at <= pending_cutoff:
            report.pending_facts += 1
            changed = True
            continue
        if created_at <= raw_cutoff and fact.source.text != REDACTED_SOURCE_TEXT:
            fact.source.text = REDACTED_SOURCE_TEXT
            fact.source.start_offset = None
            fact.source.end_offset = None
            report.source_excerpts += 1
            changed = True
        retained_facts.append(fact)
    profile.facts = retained_facts

    retained_fact_ids = {fact.id for fact in retained_facts}
    retained_reference_ids = [
        fact_id for fact_id in profile.reference_learning_fact_ids if fact_id in retained_fact_ids
    ]
    if retained_reference_ids != profile.reference_learning_fact_ids:
        profile.reference_learning_fact_ids = retained_reference_ids
        changed = True
    event_cutoff = now - timedelta(days=policy.rejected_fact_days)
    retained_events = [
        event
        for event in profile.review_events
        if event.fact_id in retained_fact_ids and _utc(event.created_at) > event_cutoff
    ]
    report.review_events += len(profile.review_events) - len(retained_events)
    if len(retained_events) != len(profile.review_events):
        profile.review_events = retained_events
        changed = True

    for progress in profile_session.sections:
        retained_ids = [
            fact_id for fact_id in progress.proposed_fact_ids if fact_id in retained_fact_ids
        ]
        if retained_ids != progress.proposed_fact_ids:
            progress.proposed_fact_ids = retained_ids
            changed = True
        if _utc(progress.updated_at) <= raw_cutoff and any(
            (
                progress.summary,
                progress.follow_up_question,
                progress.clarification_answer,
            )
        ):
            progress.summary = None
            progress.follow_up_question = None
            progress.clarification_answer = None
            changed = True

    if _utc(profile.updated_at) <= raw_cutoff and profile.unresolved_questions:
        profile.unresolved_questions = []
        changed = True
    return changed


def run_retention(
    database: Database,
    policy: RetentionPolicy,
    *,
    now: datetime | None = None,
) -> RetentionReport:
    """Apply finite retention without logging personal content or identifiers."""

    current = _utc(now or datetime.now(timezone.utc))
    token_cutoff = current - timedelta(days=policy.token_record_days)
    auth_attempt_cutoff = current - timedelta(days=policy.auth_attempt_days)
    raw_cutoff = current - timedelta(days=policy.raw_compass_days)
    legacy_cv_cutoff = current - timedelta(hours=policy.legacy_cv_hours)
    telemetry_cutoff = current - timedelta(days=policy.provider_telemetry_days)
    application_draft_cutoff = current - timedelta(days=policy.application_draft_days)
    product_feedback_cutoff = current - timedelta(days=policy.product_feedback_days)
    report = RetentionReport()

    with database.session_factory.begin() as session:
        report.expired_sessions = _deleted_rows(
            session.execute(delete(AuthSessionRow).where(AuthSessionRow.expires_at <= current))
        )
        report.invitation_records = _deleted_rows(
            session.execute(
                delete(AccountInvitationRow).where(
                    or_(
                        AccountInvitationRow.expires_at <= token_cutoff,
                        AccountInvitationRow.accepted_at <= token_cutoff,
                        AccountInvitationRow.revoked_at <= token_cutoff,
                    )
                )
            )
        )
        report.recovery_records = _deleted_rows(
            session.execute(
                delete(PasswordResetRow).where(
                    or_(
                        PasswordResetRow.expires_at <= token_cutoff,
                        PasswordResetRow.used_at <= token_cutoff,
                    )
                )
            )
        )
        report.auth_attempts = _deleted_rows(
            session.execute(
                delete(AuthAttemptRow).where(AuthAttemptRow.created_at <= auth_attempt_cutoff)
            )
        )
        report.conversation_messages = _deleted_rows(
            session.execute(
                delete(ConversationMessageRow).where(
                    ConversationMessageRow.created_at <= raw_cutoff
                )
            )
        )
        report.legacy_cv_documents = _deleted_rows(
            session.execute(
                delete(CvDocumentRow).where(CvDocumentRow.uploaded_at <= legacy_cv_cutoff)
            )
        )
        report.model_invocations = _deleted_rows(
            session.execute(
                delete(ModelInvocationRow).where(ModelInvocationRow.finished_at <= telemetry_cutoff)
            )
        )
        report.provider_operations = _deleted_rows(
            session.execute(
                delete(ProviderOperationRow).where(
                    ProviderOperationRow.finished_at <= telemetry_cutoff
                )
            )
        )
        report.application_drafts = _deleted_rows(
            session.execute(
                delete(ApplicationDraftRow).where(
                    ApplicationDraftRow.updated_at <= application_draft_cutoff
                )
            )
        )
        report.product_feedback = _deleted_rows(
            session.execute(
                delete(ProductFeedbackRow).where(
                    ProductFeedbackRow.updated_at <= product_feedback_cutoff
                )
            )
        )

        for row in session.scalars(select(ProfileWorkspaceRow)).all():
            profile_session = ProfileSession.model_validate_json(row.session_json)
            if _minimise_profile(
                profile_session,
                now=current,
                policy=policy,
                report=report,
            ):
                row.session_json = profile_session.model_dump_json()
                report.profile_workspaces_sanitized += 1

    return report


def _print_report(report: RetentionReport) -> None:
    print(
        f"Retention completed: {report.total_changes} change(s) across privacy-controlled records."
    )
    for label, count in asdict(report).items():
        if count:
            print(f"{label}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply BetterOption retention rules.")
    parser.add_argument("command", choices=("once", "loop"), nargs="?", default="once")
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings.database_url)
    policy = RetentionPolicy.from_settings(settings)

    while True:
        _print_report(run_retention(database, policy))
        if args.command == "once":
            return 0
        Event().wait(settings.retention_worker_interval_hours * 60 * 60)


if __name__ == "__main__":
    raise SystemExit(main())
