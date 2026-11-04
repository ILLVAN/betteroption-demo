from __future__ import annotations

from datetime import datetime, timezone

from betteroption.application_guidance import (
    ApplicationGuidance,
    ApplicationGuidanceEntry,
    extract_application_guidance,
    merge_application_guidance,
)
from betteroption.discovery import DiscoveryQuery, _web_search_texts
from betteroption.jobs import (
    JobPosting,
    JobSourceType,
    JobUrlStatus,
    normalize_placeholder_employer,
)
from betteroption.providers.openai_job import _minimize_job_text_for_provider


NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def _url_job(*, company: str, url: str, source_text: str) -> JobPosting:
    return JobPosting(
        title="Registered Midwife",
        company=company,
        location="Leipzig, Germany",
        summary="Support families in a clinical maternity team.",
        source_type=JobSourceType.URL_TEXT,
        source_name=url,
        source_url=url,
        requested_url=url,
        url_status=JobUrlStatus.VERIFIED_REACHABLE,
        url_http_status=200,
        url_checked_at=NOW,
        source_text=source_text,
    )


def test_german_market_role_queries_cover_both_languages_without_keyword_wall() -> None:
    query = DiscoveryQuery(
        text="Midwife",
        location="Leipzig, Germany",
        desired_terms=["Midwife"],
        excluded_terms=["military", "defence industry"],
    )

    searches = _web_search_texts(query)

    assert 2 <= len(searches) <= 16
    assert any('"Midwife"' in search for search in searches)
    assert any('"hebamme"' in search.casefold() for search in searches)
    assert all("-military" in search for search in searches)
    assert all("defence industry" not in search for search in searches)
    assert all(" OR " not in search for search in searches)


def test_german_role_input_gets_the_symmetric_english_search_variant() -> None:
    searches = _web_search_texts(
        DiscoveryQuery(
            text="Hebamme",
            location="Deutschland",
            desired_terms=["Hebamme"],
        )
    )

    assert any('"Hebamme"' in search for search in searches)
    assert any('"midwife"' in search.casefold() for search in searches)


def test_first_party_host_brand_resolves_generic_employer_only_with_source_proof() -> None:
    job = _url_job(
        company="Unknown",
        url="https://www.nurselo.com/jobs/hebamme-entbindungspfleger-in-leipzig",
        source_text=(
            "Willkommen bei Nurselo. Nurselo versteht sich als moderner, persönlicher "
            "und leistungsstarker Arbeitgeber für examinierte Pflegefachkräfte."
        ),
    )

    corrected = normalize_placeholder_employer(job)

    assert corrected.company == "Nurselo"
    assert any("first-party host brand" in warning for warning in corrected.extraction_warnings)


def test_homepage_proof_can_resolve_but_unproved_and_ats_hosts_stay_unknown() -> None:
    first_party = _url_job(
        company="Unknown",
        url="https://nurselo.com/jobs/42",
        source_text="Registered Midwife in Leipzig. Join a supportive maternity team.",
    )
    ats = _url_job(
        company="Unknown",
        url="https://jobs.lever.co/nurselo/42",
        source_text="Nurselo is an employer. Join Nurselo as a registered midwife.",
    )

    assert normalize_placeholder_employer(first_party).company == "Unknown"
    assert (
        normalize_placeholder_employer(
            first_party,
            homepage_text="Welcome to Nurselo. Nurselo is a specialist healthcare employer.",
        ).company
        == "Nurselo"
    )
    assert normalize_placeholder_employer(ats).company == "Unknown"


def test_job_specific_application_email_beats_support_and_privacy_mailboxes() -> None:
    source = (
        "Technical support: support@example.eu. Privacy enquiries: privacy@example.eu. "
        "So bewerben Sie sich: Senden Sie Ihre Bewerbung und Ihren Lebenslauf per E-Mail "
        "an bewerbung@example.eu."
    )

    guidance = extract_application_guidance(
        source,
        source_url="https://careers.example.eu/jobs/42",
    )
    minimized = _minimize_job_text_for_provider(source)

    assert guidance.contact_email is not None
    assert guidance.contact_email.value == "bewerbung@example.eu"
    assert "support@example.eu" not in minimized
    assert "privacy@example.eu" not in minimized
    assert "bewerbung@example.eu" not in minimized


def test_deterministic_job_mailbox_replaces_legacy_model_footer_mailbox() -> None:
    source = (
        "Privacy: privacy@example.eu. Apply by email: send your application to jobs@example.eu."
    )
    deterministic = extract_application_guidance(
        source,
        source_url="https://careers.example.eu/jobs/42",
    )
    legacy_model = ApplicationGuidance(
        contact_email=ApplicationGuidanceEntry(
            value="privacy@example.eu",
            evidence_quote="Privacy: privacy@example.eu.",
        )
    )

    merged = merge_application_guidance(deterministic, legacy_model)

    assert merged.contact_email is not None
    assert merged.contact_email.value == "jobs@example.eu"


def test_ordinary_privacy_mailbox_is_not_presented_as_an_application_destination() -> None:
    guidance = extract_application_guidance(
        "Privacy contact: privacy@example.eu. This role builds a data platform.",
        source_url="https://careers.example.eu/jobs/42",
    )

    assert guidance.contact_email is None


def test_schema_label_is_removed_from_merged_postal_address_value() -> None:
    source_value = "PostalAddress Friedrichstraße 41, 01067 Dresden Sachsen DE"
    model = ApplicationGuidance(
        postal_address=ApplicationGuidanceEntry(
            value=source_value,
            evidence_quote=source_value,
        )
    )

    merged = merge_application_guidance(ApplicationGuidance(), model)

    assert merged.postal_address is not None
    assert merged.postal_address.value == "Friedrichstraße 41, 01067 Dresden Sachsen DE"
    assert merged.postal_address.evidence_quote == source_value


def test_repeated_schema_representation_is_shown_as_one_published_address() -> None:
    source_value = "Siemensstraße 30, 63755 DE PostalAddress Siemensstraße 30 Alzenau 63755 DE"
    model = ApplicationGuidance(
        postal_address=ApplicationGuidanceEntry(
            value=source_value,
            evidence_quote=source_value,
        )
    )

    merged = merge_application_guidance(ApplicationGuidance(), model)

    assert merged.postal_address is not None
    assert merged.postal_address.value == "Siemensstraße 30 Alzenau 63755 DE"
    assert merged.postal_address.evidence_quote == source_value


def test_distinct_published_addresses_remain_visible() -> None:
    source_value = (
        "PostalAddress Main Street 1, 10115 Berlin PostalAddress Branch Road 2, 20095 Hamburg"
    )
    model = ApplicationGuidance(
        postal_address=ApplicationGuidanceEntry(
            value=source_value,
            evidence_quote=source_value,
        )
    )

    merged = merge_application_guidance(ApplicationGuidance(), model)

    assert merged.postal_address is not None
    assert merged.postal_address.value == (
        "Main Street 1, 10115 Berlin / Branch Road 2, 20095 Hamburg"
    )
