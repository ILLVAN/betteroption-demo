from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from sqlalchemy import create_engine, inspect, text

from betteroption.database import Database, _migration_config
from betteroption.extraction import SectionExtraction
from betteroption.job_repository import (
    JobObservationRow,
    JobRecordRow,
    JobRevisionRow,
    JobUrlAliasRow,
)
from betteroption.llm import (
    InMemoryInvocationRecorder,
    InvocationOutcome,
    LLMTask,
    ModelInvocation,
    ModelPolicy,
    ModelRoute,
    TokenUsage,
)
from betteroption.profile import ProfileSection
from betteroption.provider_registry import ProviderRegistry
from betteroption.providers.openai import OpenAIProfileExtractor
from betteroption.settings import Settings
from betteroption.session import new_session
from betteroption.telemetry import SqlAlchemyInvocationRecorder


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)


def database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_new_database_is_upgraded_to_current_schema(tmp_path: Path) -> None:
    database = Database(database_url(tmp_path / "new.db"))

    tables = set(inspect(database.engine).get_table_names())
    match_run_columns = {
        column["name"] for column in inspect(database.engine).get_columns("match_runs")
    }
    with database.engine.connect() as connection:
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one()

    assert "job_records" in tables
    assert "model_invocations" in tables
    assert "profile_workspaces" in tables
    assert "conversation_messages" in tables
    assert "match_runs" in tables
    assert "provider_unpriced_operations" in match_run_columns
    assert "match_results" in tables
    assert "result_access_grants" in tables
    assert "job_interactions" in tables
    assert "job_interaction_events" in tables
    assert "commute_estimates" in tables
    assert "cv_documents" in tables
    assert "provider_operations" in tables
    assert "background_tasks" in tables
    assert "explore_searches" in tables
    assert "accounts" in tables
    assert "auth_sessions" in tables
    assert "account_personas" in tables
    assert "application_drafts" in tables
    assert "persona_employer_reputation_ratings" in tables
    assert "persona_job_ratings" in tables
    assert "background_single_job_matches" in tables
    assert "job_poster_access" in tables
    assert "employer_job_postings" in tables
    assert "account_bootstrap" in tables
    assert "product_feedback" in tables
    assert revision == "0033_background_task_leases"


def test_v071d_accounts_workspaces_and_sessions_receive_separate_main_personas(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path / "v071d.db")
    current = Database(url)
    current.engine.dispose()
    command.downgrade(_migration_config(url), "0017_invitation_onboarding")

    legacy_engine = create_engine(url)
    account_ids: list[str] = []
    workspace_ids: list[str] = []
    now = datetime.now(timezone.utc)
    with legacy_engine.begin() as connection:
        for index, name in enumerate(("primary", "secondary"), start=1):
            account_id = str(uuid4())
            session = new_session()
            workspace_id = str(session.id)
            account_ids.append(account_id)
            workspace_ids.append(workspace_id)
            connection.execute(
                text(
                    "INSERT INTO accounts "
                    "(id, email, display_name, username_normalized, password_hash, "
                    "email_verified_at, created_at, updated_at) "
                    "VALUES (:id, :email, :name, :normalized, :password_hash, "
                    ":verified, :created, :updated)"
                ),
                {
                    "id": account_id,
                    "email": f"{name}@example.com",
                    "name": name,
                    "normalized": name,
                    "password_hash": "legacy-test-hash",
                    "verified": now,
                    "created": now,
                    "updated": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO profile_workspaces "
                    "(id, account_id, session_json, active, created_at, updated_at) "
                    "VALUES (:id, :account_id, :session_json, :active, :created, :updated)"
                ),
                {
                    "id": workspace_id,
                    "account_id": account_id,
                    "session_json": session.model_dump_json(),
                    "active": True,
                    "created": now,
                    "updated": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(id, account_id, token_hash, created_at, last_seen_at, expires_at) "
                    "VALUES (:id, :account_id, :token_hash, :created, :seen, :expires)"
                ),
                {
                    "id": str(uuid4()),
                    "account_id": account_id,
                    "token_hash": f"{index:064d}",
                    "created": now,
                    "seen": now,
                    "expires": now + timedelta(days=30),
                },
            )
    legacy_engine.dispose()

    upgraded = Database(url)
    with upgraded.engine.connect() as connection:
        personas = connection.execute(
            text("SELECT account_id, id, name FROM account_personas ORDER BY account_id")
        ).all()
        workspace_owners = dict(
            connection.execute(text("SELECT id, persona_id FROM profile_workspaces")).all()
        )
        session_personas = connection.execute(
            text("SELECT account_id, active_persona_id FROM auth_sessions")
        ).all()

    assert len(personas) == 2
    persona_by_account = {
        account_id: persona_id for account_id, persona_id, name in personas if name == "Main"
    }
    assert set(persona_by_account) == set(account_ids)
    for account_id, workspace_id in zip(account_ids, workspace_ids, strict=True):
        assert workspace_owners[workspace_id] == persona_by_account[account_id]
    assert dict(session_personas) == persona_by_account


def test_existing_v060_corpus_is_adopted_without_data_loss(tmp_path: Path) -> None:
    url = database_url(tmp_path / "legacy.db")
    legacy_engine = create_engine(url)
    JobRecordRow.__table__.create(legacy_engine)
    JobObservationRow.__table__.create(legacy_engine)
    JobRevisionRow.__table__.create(legacy_engine)
    JobUrlAliasRow.__table__.create(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            JobRecordRow.__table__.insert().values(
                id="11111111-1111-1111-1111-111111111111",
                canonical_url="https://jobs.example.com/123",
                availability="unreachable",
                last_observation_kind="unreachable",
                current_revision_id=None,
                current_content_hash=None,
                first_seen_at=None,
                last_seen_at=None,
                last_checked_at=NOW,
                last_http_status=None,
                unavailable_reason="Legacy marker",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    legacy_engine.dispose()

    upgraded = Database(url)

    with upgraded.engine.connect() as connection:
        marker = connection.execute(text("select unavailable_reason from job_records")).scalar_one()
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one()
    assert marker == "Legacy marker"
    assert revision == "0033_background_task_leases"
    assert "model_invocations" in inspect(upgraded.engine).get_table_names()
    assert "profile_workspaces" in inspect(upgraded.engine).get_table_names()
    assert "provider_operations" in inspect(upgraded.engine).get_table_names()
    assert "background_tasks" in inspect(upgraded.engine).get_table_names()


def test_model_policy_and_registry_select_by_task() -> None:
    policy = ModelPolicy(
        [
            ModelRoute(
                task=LLMTask.PROFILE_EXTRACTION,
                provider="example",
                model="profile-model",
                prompt_version="profile-test",
            ),
            ModelRoute(
                task=LLMTask.JOB_EXTRACTION,
                provider="example",
                model="job-model",
                prompt_version="job-test",
            ),
        ]
    )
    registry = ProviderRegistry()
    registry.register_profile("example", lambda *, route, recorder: (route, recorder))
    recorder = InMemoryInvocationRecorder()

    route, selected_recorder = registry.build_profile(policy, recorder)

    assert route.model == "profile-model"
    assert selected_recorder is recorder


def test_settings_keep_profile_and_job_models_independently_routable() -> None:
    settings = Settings(
        llm_provider="openai",
        openai_model="fallback",
        profile_extraction_model="profile-specialist",
        job_extraction_model="job-specialist",
    )

    policy = settings.model_policy()

    assert policy.route(LLMTask.PROFILE_EXTRACTION).model == "profile-specialist"
    assert policy.route(LLMTask.JOB_EXTRACTION).model == "job-specialist"


def test_openai_adapter_records_usage_without_storing_user_text() -> None:
    result = SectionExtraction(summary="A direction", facts=[], follow_up_question=None)
    response = SimpleNamespace(
        output_parsed=result,
        usage=SimpleNamespace(input_tokens=110, output_tokens=40, total_tokens=150),
    )
    client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: response))
    recorder = InMemoryInvocationRecorder()
    extractor = OpenAIProfileExtractor(
        model="test-model",
        client=client,
        recorder=recorder,
    )

    extractor.extract(ProfileSection.DIRECTION, "My private career preference")

    assert len(recorder.invocations) == 1
    invocation = recorder.invocations[0]
    assert invocation.outcome == InvocationOutcome.SUCCEEDED
    assert invocation.usage.total_tokens == 150
    assert "private" not in invocation.model_dump_json().casefold()


def test_sqlalchemy_recorder_round_trips_operational_metadata(tmp_path: Path) -> None:
    database = Database(database_url(tmp_path / "telemetry.db"))
    recorder = SqlAlchemyInvocationRecorder(database)
    recorder.record(
        ModelInvocation(
            task=LLMTask.JOB_EXTRACTION,
            provider="openai",
            model="test-model",
            prompt_version="job-test",
            outcome=InvocationOutcome.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
            latency_ms=14,
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            estimated_cost_usd=0.001,
        )
    )

    recent = recorder.list_recent()
    summary = recorder.summary()

    assert recent[0].task == LLMTask.JOB_EXTRACTION
    assert recent[0].usage.total_tokens == 15
    assert summary.total_calls == 1
    assert summary.failed_calls == 0
    assert summary.estimated_cost_usd == 0.001
