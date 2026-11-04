from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from betteroption.accounts import AccountRepository, RegistrationMode
from betteroption.container import ApplicationContainer
from betteroption.database import Database
from betteroption.discovery import DiscoveryQuery
from betteroption.job_posters import (
    BetterOptionPostedJobProvider,
    EmployerPostingStatus,
    JobPosterAccessStatus,
    JobPosterError,
    JobPosterRepository,
)
from betteroption.settings import Settings
from betteroption.web import create_app


PASSWORD = "Poster-password-123"


def _account(accounts: AccountRepository, email: str, name: str):
    return accounts.create(
        email,
        name,
        PASSWORD,
        registration_mode=RegistrationMode.OPEN,
    )


def _approved_repository() -> tuple[JobPosterRepository, UUID, UUID]:
    database = Database("sqlite:///:memory:")
    accounts = AccountRepository(database)
    poster = _account(accounts, "poster@nurselo.example", "Poster")
    operator = _account(accounts, "operator@example.org", "Operator")
    repository = JobPosterRepository(database)
    request = repository.request_access(
        poster.id,
        company_name="Nurselo",
        company_website="https://nurselo.example",
        work_email="jobs@nurselo.example",
    )
    assert request.status == JobPosterAccessStatus.PENDING
    approved = repository.review_access(
        poster.id,
        approved=True,
        reviewer_account_id=operator.id,
        reviewer_note="Company domain and representative checked manually.",
    )
    assert approved.status == JobPosterAccessStatus.APPROVED
    return repository, poster.id, operator.id


def test_poster_access_fails_closed_and_requires_company_identity() -> None:
    database = Database("sqlite:///:memory:")
    accounts = AccountRepository(database)
    poster = _account(accounts, "person@example.org", "Poster")
    repository = JobPosterRepository(database)

    with pytest.raises(JobPosterError, match="company email"):
        repository.request_access(
            poster.id,
            company_name="Example Employer",
            company_website="https://example-employer.test",
            work_email="personal@gmail.com",
        )

    with pytest.raises(JobPosterError, match="Explain the relationship"):
        repository.request_access(
            poster.id,
            company_name="Example Employer",
            company_website="https://example-employer.test",
            work_email="jobs@different-company.test",
        )

    for private_url in (
        "https://localhost/company",
        "https://127.0.0.1/company",
        "https://10.0.0.8/company",
        "https://intranet.local/company",
    ):
        with pytest.raises(JobPosterError, match="public HTTPS URL"):
            repository.request_access(
                poster.id,
                company_name="Example Employer",
                company_website=private_url,
                work_email="jobs@example-employer.test",
                requester_note="Domain relationship supplied for manual review.",
            )


def test_approved_poster_can_publish_to_first_party_explore_source() -> None:
    repository, poster_id, _operator_id = _approved_repository()
    posting = repository.create_posting(
        poster_id,
        title="Hebamme / Midwife",
        employer_name="Nurselo",
        location="Leipzig, Germany",
        work_model="On-site",
        summary="Midwifery role supporting parents and newborns in Leipzig.",
        description=(
            "Join our qualified maternity team in Leipzig. You counsel parents, support "
            "births and post-partum care, and work with a multi-professional clinical team. "
            "Completed midwifery training is required."
        ),
        application_url="https://nurselo.example/jobs/midwife",
        publish=True,
    )
    assert posting.status == EmployerPostingStatus.PUBLISHED

    provider = BetterOptionPostedJobProvider(
        repository,
        public_base_url="https://worklifebalance.example",
    )
    results = provider.search(
        DiscoveryQuery(
            text="Midwife",
            location="Leipzig",
            desired_terms=["midwifery"],
        )
    )

    assert len(results) == 1
    assert results[0].company == "Nurselo"
    assert results[0].provider == "betteroption-posted"
    assert str(results[0].source_url).endswith(f"/published-jobs/{posting.id}")
    assert repository.get_published(posting.id) == posting


def test_poster_cannot_publish_for_an_unapproved_company_or_other_account() -> None:
    repository, poster_id, _operator_id = _approved_repository()
    with pytest.raises(JobPosterError, match="must match"):
        repository.create_posting(
            poster_id,
            title="Software Engineer",
            employer_name="Different Company",
            location="Remote",
            work_model="Remote",
            summary="A product engineering role.",
            description="Build and maintain the public product. " * 8,
            application_email="jobs@different.example",
            publish=True,
        )

    database = repository.database
    accounts = AccountRepository(database)
    outsider = _account(accounts, "outsider@example.org", "Outsider")
    with pytest.raises(JobPosterError, match="Verified job-poster access"):
        repository.create_posting(
            outsider.id,
            title="Software Engineer",
            employer_name="Nurselo",
            location="Remote",
            work_model="Remote",
            summary="A product engineering role.",
            description="Build and maintain the public product. " * 8,
            application_email="jobs@nurselo.example",
            publish=True,
        )


def test_live_posting_stays_valid_and_access_revocation_withdraws_it() -> None:
    repository, poster_id, operator_id = _approved_repository()
    posting = repository.create_posting(
        poster_id,
        title="Software Engineer",
        employer_name="Nurselo",
        location="Remote",
        work_model="Remote",
        summary="A public product-engineering role.",
        description="Build, review, test, and maintain the public product. " * 6,
        application_email="jobs@nurselo.example",
        publish=True,
    )

    with pytest.raises(JobPosterError, match="120 characters"):
        repository.update_posting(
            poster_id,
            posting.id,
            title=posting.title,
            employer_name=posting.employer_name,
            location=posting.location,
            work_model=posting.work_model,
            summary=posting.summary,
            description="Too short for a live posting.",
            application_email=posting.application_email,
        )
    with pytest.raises(JobPosterError, match="application URL or application email"):
        repository.update_posting(
            poster_id,
            posting.id,
            title=posting.title,
            employer_name=posting.employer_name,
            location=posting.location,
            work_model=posting.work_model,
            summary=posting.summary,
            description=posting.description,
        )

    unchanged = repository.get_published(posting.id)
    assert unchanged is not None
    assert unchanged.description == posting.description
    repository.review_access(
        poster_id,
        approved=False,
        reviewer_account_id=operator_id,
        reviewer_note="Representative authorization could no longer be confirmed.",
    )
    assert repository.get_published(posting.id) is None
    assert repository.list_owned(poster_id)[0].status == EmployerPostingStatus.WITHDRAWN
    with pytest.raises(JobPosterError, match="Verified job-poster access"):
        repository.publish(poster_id, posting.id)


def test_approved_poster_cannot_read_or_change_another_posters_job() -> None:
    repository, first_poster_id, operator_id = _approved_repository()
    first_posting = repository.create_posting(
        first_poster_id,
        title="Software Engineer",
        employer_name="Nurselo",
        location="Leipzig",
        work_model="Hybrid",
        summary="A public product-engineering role.",
        description="Build, review, test, and maintain the public product. " * 6,
        application_email="jobs@nurselo.example",
    )
    second = _account(AccountRepository(repository.database), "jobs@other.example", "Other")
    repository.request_access(
        second.id,
        company_name="Other Company",
        company_website="https://other.example",
        work_email="jobs@other.example",
    )
    repository.review_access(
        second.id,
        approved=True,
        reviewer_account_id=operator_id,
        reviewer_note="Second company checked independently.",
    )

    assert repository.get_owned(second.id, first_posting.id) is None
    with pytest.raises(JobPosterError, match="Job posting not found"):
        repository.update_posting(
            second.id,
            first_posting.id,
            title="Changed",
            employer_name="Other Company",
            location="Remote",
            work_model="Remote",
            summary="An attempted cross-account change.",
            description="This must never replace another account's posting. " * 6,
            application_email="jobs@other.example",
        )


def test_hosted_job_posting_requires_explicit_readiness() -> None:
    assert Settings(app_environment="local").employer_job_posting_available
    assert not Settings(app_environment="staging").employer_job_posting_available
    assert not Settings(
        app_environment="staging",
        employer_job_posting_enabled=True,
        legal_review_completed=True,
        incident_plan_ready=True,
        operator_emails="operator@example.org",
    ).employer_job_posting_available
    assert Settings(
        app_environment="staging",
        employer_job_posting_enabled=True,
        legal_review_completed=True,
        processor_review_completed=True,
        incident_plan_ready=True,
        operator_emails="operator@example.org",
    ).employer_job_posting_available
    disabled_container = ApplicationContainer(
        Settings(
            database_url="sqlite:///:memory:",
            app_environment="staging",
            background_worker_enabled=False,
        )
    )
    disabled_mesh = disabled_container.job_discovery_provider()
    assert not any(
        isinstance(provider, BetterOptionPostedJobProvider)
        for provider in disabled_mesh.primary_providers
    )


def test_web_poster_flow_requires_operator_approval_and_stays_public_only(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'poster-web.db').as_posix()}",
        auth_mode="accounts",
        registration_mode="open",
        operator_emails="operator@example.org",
        background_worker_enabled=False,
        app_environment="local",
    )
    container = ApplicationContainer(settings)
    operator = _account(container.accounts, "operator@example.org", "Operator")
    poster = _account(container.accounts, "jobs@nurselo.example", "Poster")
    app = create_app(container, data_directory=tmp_path / "data")

    def authenticated(account) -> TestClient:
        client = TestClient(app)
        session = container.accounts.create_session(account, ttl=timedelta(hours=1))
        client.cookies.set("betteroption_session", session.token)
        return client

    poster_client = authenticated(poster)
    requested = poster_client.post(
        "/employer/jobs/request",
        data={
            "company_name": "Nurselo",
            "company_website": "https://nurselo.example",
            "work_email": "jobs@nurselo.example",
        },
        follow_redirects=False,
    )
    blocked = poster_client.post(
        "/employer/jobs",
        data={
            "title": "Hebamme / Midwife",
            "employer_name": "Nurselo",
            "location": "Leipzig",
            "work_model": "On-site",
            "summary": "Qualified midwifery role in Leipzig.",
            "description": "Support parents, births, and post-partum care. " * 8,
            "application_email": "jobs@nurselo.example",
            "confirm_public_business_data": "true",
            "publish_now": "true",
        },
        follow_redirects=False,
    )
    assert requested.status_code == 303
    assert "error=" in blocked.headers["location"]

    operator_client = authenticated(operator)
    operations = operator_client.get("/operations")
    approved = operator_client.post(
        f"/operations/job-posters/{poster.id}/review",
        data={
            "decision": "approve",
            "reviewer_note": "Company domain checked.",
        },
        follow_redirects=False,
    )
    assert operations.status_code == 200
    assert "Nurselo" in operations.text
    assert approved.status_code == 303

    created = poster_client.post(
        "/employer/jobs",
        data={
            "title": "Hebamme / Midwife",
            "employer_name": "Nurselo",
            "location": "Leipzig",
            "work_model": "On-site",
            "summary": "Qualified midwifery role in Leipzig.",
            "description": "Support parents, births, and post-partum care. " * 8,
            "application_email": "jobs@nurselo.example",
            "confirm_public_business_data": "true",
            "publish_now": "true",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    posting = container.job_posters.list_published()[0]

    with TestClient(app) as public_client:
        public_page = public_client.get(f"/published-jobs/{posting.id}")
        private_workspace = public_client.get("/employer/jobs", follow_redirects=False)
    assert public_page.status_code == 200
    assert "Hebamme / Midwife" in public_page.text
    assert "candidate profiles" not in public_page.text.casefold()
    assert private_workspace.status_code == 303
    assert private_workspace.headers["location"].startswith("/login")

    settings.app_environment = "staging"
    settings.employer_job_posting_enabled = False
    disabled_public_page = poster_client.get(f"/published-jobs/{posting.id}")
    disabled_mutation = poster_client.post(
        f"/employer/jobs/{posting.id}/status",
        data={"action": "withdraw"},
        headers={"origin": "http://testserver"},
        follow_redirects=False,
    )
    assert disabled_public_page.status_code == 404
    assert disabled_mutation.status_code == 303
    assert "error=" in disabled_mutation.headers["location"]
    assert container.job_posters.get_published(posting.id) is not None
