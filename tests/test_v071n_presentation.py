from __future__ import annotations

from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.presentation import format_job_location, format_location_text, job_is_remote_only


def _job(*, location: str, facts: list[JobFact] | None = None) -> JobPosting:
    return JobPosting(
        title="Platform Engineer",
        company="Example GmbH",
        location=location,
        summary="Operate a dependable platform.",
        source_type=JobSourceType.MANUAL_TEXT,
        source_name="manual input",
        source_text="Operate a dependable platform. Fully remote within Germany.",
        facts=facts or [],
    )


def test_schema_org_postal_address_leak_is_presented_as_locations() -> None:
    raw = (
        "PostalAddress Deutschland Frankfurt am Main Hessen 60322 Nicht vorhanden "
        "PostalAddress Deutschland Frankfurt am Main Hessen 60311 Nicht vorhanden"
    )

    assert format_location_text(raw) == (
        "60322 Frankfurt am Main, Hessen / 60311 Frankfurt am Main, Hessen"
    )


def test_explicit_remote_only_job_has_a_clean_remote_label() -> None:
    job = _job(
        location="Berlin",
        facts=[
            JobFact(
                key="work_model.remote",
                value="fully remote",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Fully remote",
            )
        ],
    )

    assert job_is_remote_only(job) is True
    assert format_job_location(job) == "Berlin · Remote"


def test_hybrid_job_is_not_mislabeled_remote_only() -> None:
    job = _job(
        location="Berlin",
        facts=[
            JobFact(
                key="work_model.remote",
                value="remote days possible in a hybrid model",
                kind=JobFactKind.CONTEXT,
                evidence_quote="remote within Germany",
            )
        ],
    )

    assert job_is_remote_only(job) is False
    assert format_job_location(job) == "Berlin"


def test_remote_only_job_uses_an_attributed_company_seat_without_routing_to_it() -> None:
    job = _job(
        location="Remote",
        facts=[
            JobFact(
                key="job.work_model.remote",
                value="fully remote",
                kind=JobFactKind.CONTEXT,
                evidence_quote="Fully remote",
            ),
            JobFact(
                key="company.location",
                value="Hamburg",
                kind=JobFactKind.CONTEXT,
                evidence_quote="within Germany",
            ),
        ],
    )

    assert format_job_location(job) == "Hamburg · Remote"
