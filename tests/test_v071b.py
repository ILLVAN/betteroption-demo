from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from betteroption.accounts import (
    AccountError,
    AccountInvitationRow,
    AccountRepository,
    AccountRow,
    AuthAttemptRow,
    RegistrationMode,
)
from betteroption.container import ApplicationContainer
from betteroption.job_repository import JobObservationKind
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType, JobUrlStatus
from betteroption.profile import EvidenceStatus
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.settings import Settings
from betteroption.url_ingestion import FetchedDocument
from betteroption.web import create_app


PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a newer correct horse battery staple"
PUBLIC_ORIGIN = "https://staging.betteroption.example"
RATE_SECRET = "0123456789abcdef" * 4
NOW = datetime.now(timezone.utc)


def account_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{(tmp_path / 'v071b.db').as_posix()}",
        "auth_mode": "accounts",
        "registration_mode": "invite_only",
        "operator_emails": "owner@example.com",
        "public_base_url": PUBLIC_ORIGIN,
        "auth_rate_limit_secret": RATE_SECRET,
        "background_worker_enabled": False,
        "employer_homepage_research": False,
    }
    values.update(overrides)
    return Settings(**values)


def create_owner(container: ApplicationContainer):
    return container.accounts.create(
        "owner@example.com",
        "Owner",
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )


def accept_invitation(
    repository: AccountRepository,
    owner_id: UUID,
    email: str,
    display_name: str,
):
    _invitation, token = repository.create_invitation(
        email,
        invited_by_account_id=owner_id,
        ttl=timedelta(hours=1),
    )
    return repository.accept_invitation(token, display_name, PASSWORD), token


def authenticated_client(
    app,
    container: ApplicationContainer,
    account,
) -> TestClient:
    client = TestClient(app, base_url=PUBLIC_ORIGIN)
    session = container.accounts.create_session(account, ttl=timedelta(hours=1))
    client.cookies.set("betteroption_session", session.token)
    return client


def seed_job(container: ApplicationContainer, slug: str) -> UUID:
    url = f"https://careers.example.com/jobs/{slug}"
    source = f"{slug.title()} Engineer at Example Products. Build useful software."
    document = FetchedDocument(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        text=source,
        fetched_at=NOW,
    )
    job = JobPosting(
        title=f"{slug.title()} Engineer",
        company="Example Products",
        location="Frankfurt",
        summary="Build useful software.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source,
        observed_at=NOW,
    )
    return container.repository.store_revision(
        document,
        job,
        JobObservationKind.NEW,
    ).id


def test_invite_only_mode_rejects_direct_account_creation(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path))

    with pytest.raises(AccountError, match="registration is disabled"):
        container.accounts.create(
            "bypass@example.com",
            "Bypass",
            PASSWORD,
            registration_mode=RegistrationMode.INVITE_ONLY,
        )


def test_invitation_is_exact_address_verified_single_use_and_hashed_at_rest(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    owner = create_owner(container)

    invitation, token = container.accounts.create_invitation(
        "  Tester@Example.com ",
        invited_by_account_id=owner.id,
        ttl=timedelta(hours=1),
    )

    with container.database.session_factory() as database_session:
        stored = database_session.get(AccountInvitationRow, str(invitation.id))
        assert stored is not None
        assert stored.email == "tester@example.com"
        assert stored.token_hash == hashlib.sha256(token.encode("ascii")).hexdigest()
        assert token not in stored.token_hash

    account = container.accounts.accept_invitation(token, "Tester", PASSWORD)
    assert account.email == "tester@example.com"
    assert account.email_verified_at is not None
    assert container.accounts.authenticate(account.email, PASSWORD) == account
    assert container.accounts.invitation_for_token(token) is None

    with pytest.raises(AccountError, match="invalid, expired, or already used"):
        container.accounts.accept_invitation(token, "Tester Again", PASSWORD)


def test_expired_and_revoked_invitations_are_rejected(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    owner = create_owner(container)
    expired, expired_token = container.accounts.create_invitation(
        "expired@example.com",
        invited_by_account_id=owner.id,
        ttl=timedelta(hours=1),
    )
    revoked, revoked_token = container.accounts.create_invitation(
        "revoked@example.com",
        invited_by_account_id=owner.id,
        ttl=timedelta(hours=1),
    )
    with container.database.session_factory.begin() as database_session:
        row = database_session.get(AccountInvitationRow, str(expired.id))
        assert row is not None
        row.expires_at = row.created_at - timedelta(seconds=1)
    assert container.accounts.revoke_invitation(revoked.id)

    for token in (expired_token, revoked_token):
        assert container.accounts.invitation_for_token(token) is None
        with pytest.raises(AccountError, match="invalid, expired, or already used"):
            container.accounts.accept_invitation(token, "Blocked", PASSWORD)


def test_password_recovery_is_single_use_and_revokes_existing_sessions(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    owner = create_owner(container)
    account, _ = accept_invitation(
        container.accounts,
        owner.id,
        "recover@example.com",
        "Recover",
    )
    old_session = container.accounts.create_session(account, ttl=timedelta(hours=1))
    _account, token = container.accounts.create_password_reset(
        account.id,
        ttl=timedelta(minutes=30),
    )

    reset_account = container.accounts.reset_password(token, NEW_PASSWORD)

    assert reset_account.id == account.id
    assert container.accounts.resolve_session(old_session.token) is None
    assert container.accounts.authenticate(account.email, PASSWORD) is None
    assert container.accounts.authenticate(account.email, NEW_PASSWORD) is not None
    assert container.accounts.password_reset_account(token) is None
    with pytest.raises(AccountError, match="invalid, expired, or already used"):
        container.accounts.reset_password(token, NEW_PASSWORD)


def test_unverified_accounts_cannot_authenticate_or_resume_sessions(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    owner = create_owner(container)
    session = container.accounts.create_session(owner, ttl=timedelta(hours=1))
    with container.database.session_factory.begin() as database_session:
        row = database_session.get(AccountRow, str(owner.id))
        assert row is not None
        row.email_verified_at = None

    assert container.accounts.authenticate(owner.email, PASSWORD) is None
    assert container.accounts.resolve_session(session.token) is None


def test_rate_limiter_blocks_after_the_limit_and_never_stores_raw_subject(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    subject = "Person@example.com|cloudflare:203.0.113.8"

    assert container.accounts.allow_auth_attempt(
        "login",
        subject,
        secret=RATE_SECRET,
        maximum=2,
        window=timedelta(minutes=15),
    )
    assert container.accounts.allow_auth_attempt(
        "login",
        subject,
        secret=RATE_SECRET,
        maximum=2,
        window=timedelta(minutes=15),
    )
    assert not container.accounts.allow_auth_attempt(
        "login",
        subject,
        secret=RATE_SECRET,
        maximum=2,
        window=timedelta(minutes=15),
    )

    expected_hash = hmac.new(
        RATE_SECRET.encode(),
        subject.casefold().encode(),
        hashlib.sha256,
    ).hexdigest()
    with container.database.session_factory() as database_session:
        rows = database_session.scalars(select(AuthAttemptRow)).all()
    assert len(rows) == 2
    assert {row.subject_hash for row in rows} == {expected_hash}
    assert all("person@example.com" not in row.subject_hash for row in rows)


def test_staging_csrf_rejects_missing_or_cross_site_origin(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path, app_environment="staging"))
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
        missing = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": PASSWORD},
        )
        cross_site = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": PASSWORD},
            headers={"Origin": "https://evil.example"},
        )
        same_site = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": PASSWORD},
            headers={"Origin": PUBLIC_ORIGIN},
        )

    assert missing.status_code == 403
    assert cross_site.status_code == 403
    assert same_site.status_code == 400


def test_cloudflare_client_header_is_ignored_until_explicitly_trusted(
    tmp_path: Path,
) -> None:
    headers = {
        "Origin": PUBLIC_ORIGIN,
        "CF-Connecting-IP": "203.0.113.42",
    }
    direct_root = tmp_path / "direct"
    trusted_root = tmp_path / "trusted"
    direct_root.mkdir()
    trusted_root.mkdir()
    direct_container = ApplicationContainer(
        account_settings(
            direct_root,
            app_environment="staging",
            auth_trust_cloudflare_headers=False,
        )
    )
    trusted_container = ApplicationContainer(
        account_settings(
            trusted_root,
            app_environment="staging",
            auth_trust_cloudflare_headers=True,
        )
    )

    for container, directory in (
        (direct_container, tmp_path / "direct-data"),
        (trusted_container, tmp_path / "trusted-data"),
    ):
        with TestClient(
            create_app(container, data_directory=directory),
            base_url=PUBLIC_ORIGIN,
        ) as client:
            response = client.post(
                "/login",
                data={"email": "nobody@example.com", "password": PASSWORD},
                headers=headers,
            )
            assert response.status_code == 400

    def stored_hash(container: ApplicationContainer) -> str:
        with container.database.session_factory() as database_session:
            row = database_session.scalar(select(AuthAttemptRow))
            assert row is not None
            return row.subject_hash

    cloudflare_hash = hmac.new(
        RATE_SECRET.encode(),
        b"nobody@example.com|cloudflare:203.0.113.42",
        hashlib.sha256,
    ).hexdigest()
    direct_hash = stored_hash(direct_container)
    assert direct_hash != cloudflare_hash
    assert stored_hash(trusted_container) == cloudflare_hash


def test_owner_can_create_one_time_fragment_invitation_after_readiness(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        account_settings(
            tmp_path,
            legal_review_completed=True,
            processor_review_completed=True,
            incident_plan_ready=True,
            backup_restore_tested=True,
        )
    )
    owner = create_owner(container)
    app = create_app(container, data_directory=tmp_path / "data")

    with authenticated_client(app, container, owner) as client:
        response = client.post(
            "/operations/invitations",
            data={"email": "tester@example.com"},
            headers={"Origin": PUBLIC_ORIGIN},
        )
        operations = client.get("/operations")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "/invite#token=" in response.text
    assert "?token=" not in response.text
    invitations = container.accounts.list_invitations()
    assert len(invitations) == 1
    assert invitations[0].email == "tester@example.com"
    assert "Verified" in operations.text


def test_invited_accounts_remain_tenant_isolated(tmp_path: Path) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    owner = create_owner(container)
    account_a, _ = accept_invitation(
        container.accounts,
        owner.id,
        "alpha@example.com",
        "Alpha",
    )
    account_b, _ = accept_invitation(
        container.accounts,
        owner.id,
        "beta@example.com",
        "Beta",
    )
    workspace_a = container.workspaces.create(account_id=account_a.id)
    container.workspaces.create(account_id=account_b.id)
    record_id = seed_job(container, "invited-alpha")
    container.results.grant_job(workspace_a.id, record_id)
    app = create_app(container, data_directory=tmp_path / "data")

    with (
        authenticated_client(app, container, account_a) as client_a,
        authenticated_client(app, container, account_b) as client_b,
    ):
        assert client_a.get(f"/jobs/{record_id}").status_code == 200
        assert client_b.get(f"/jobs/{record_id}").status_code == 404
        assert client_a.get(f"/profile/{workspace_a.id}").status_code == 200
        assert client_b.get(f"/profile/{workspace_a.id}").status_code == 404


def test_foreign_account_cannot_confirm_or_reject_a_learned_profile_fact(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(account_settings(tmp_path))
    owner = create_owner(container)
    account_a, _ = accept_invitation(
        container.accounts,
        owner.id,
        "learn-alpha@example.com",
        "Learn Alpha",
    )
    account_b, _ = accept_invitation(
        container.accounts,
        owner.id,
        "learn-beta@example.com",
        "Learn Beta",
    )
    workspace_a = container.workspaces.create(account_id=account_a.id)
    workflow_a = ProfileWorkflowService(container.workspaces, account_id=account_a.id)
    learned = workflow_a.upsert_verified_reference(
        workspace_a.id,
        requested_url="https://careers.example.com/jobs/learned-alpha",
        resolved_url="https://careers.example.com/jobs/learned-alpha",
        http_status=200,
        verified_at=NOW,
        positives=["Technical ownership"],
        negatives=[],
        learning_enabled=True,
        learning_scope=["role"],
        job=JobPosting(
            title="Platform Engineer",
            company="Example Products",
            location="Frankfurt",
            summary="Own technical delivery.",
            source_type=JobSourceType.SAMPLE,
            source_name="tenant learning test",
            source_text="Own technical delivery.",
            facts=[
                JobFact(
                    key="role.responsibility",
                    value="technical ownership",
                    kind=JobFactKind.CONTEXT,
                    evidence_quote="Own technical delivery",
                )
            ],
        ),
    )
    learned_fact_id = learned.session.profile.reference_learning_fact_ids[0]
    app = create_app(container, data_directory=tmp_path / "data")

    with authenticated_client(app, container, account_b) as client_b:
        for action in ("confirm", "reject"):
            response = client_b.post(
                f"/profile/{workspace_a.id}/facts/{learned_fact_id}",
                data={"action": action, "return_to": "compass"},
                headers={"Origin": PUBLIC_ORIGIN},
                follow_redirects=False,
            )
            assert response.status_code == 303

            unchanged = container.workspaces.get(workspace_a.id, account_id=account_a.id)
            assert unchanged is not None
            learned_fact = next(
                fact for fact in unchanged.session.profile.facts if fact.id == learned_fact_id
            )
            assert learned_fact.evidence_status == EvidenceStatus.INFERRED
            assert learned_fact.needs_confirmation is True


def test_blank_cost_environment_value_is_invalid_but_explicit_zero_is_unpriced(
    monkeypatch,
) -> None:
    variable = "BETTEROPTION_OPENAI_INPUT_COST_PER_MILLION_USD"
    monkeypatch.setenv(variable, "")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv(variable, "0")
    assert Settings(_env_file=None).openai_input_cost_per_million_usd == 0
