from __future__ import annotations

from datetime import datetime, timezone

import pytest

from betteroption.application_guidance import (
    ApplicationChannel,
    GuidanceProvenance,
    extract_application_guidance,
)
from betteroption.job_extraction import (
    ApplicationGuidanceDraft,
    ApplicationGuidanceEntryDraft,
    JobExtraction,
    UnverifiedEvidenceError,
)
from betteroption.providers.openai_job import _minimize_job_text_for_provider


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
URL = "https://careers.example.eu/jobs/42"


def test_german_application_guidance_extracts_obvious_contact_and_submission_data() -> None:
    source = """So bewirbst du dich
Bitte bewirb dich ausschließlich über unser Online-Karriereportal unter https://jobs.example.de/apply/42 und lade Lebenslauf, Anschreiben sowie relevante Zeugnisse hoch.
Die Upload-Datei darf maximal 10 MB und das Anschreiben maximal 2 Seiten umfassen.
Ansprechpartnerin: Frau Dr. Lena Weiß, Senior Recruiterin
E-Mail: lena.weiss@example.de
Telefon: +49 30 1234 5678
Bewerbungsschluss: 30. September 2026
"""

    guidance = extract_application_guidance(source, source_url=URL)

    assert guidance.contact_name is not None
    assert guidance.contact_name.value == "Frau Dr. Lena Weiß"
    assert guidance.contact_role is not None
    assert guidance.contact_role.value == "Senior Recruiterin"
    assert guidance.contact_email is not None
    assert guidance.contact_email.value == "lena.weiss@example.de"
    assert guidance.contact_phone is not None
    assert guidance.contact_phone.value == "+49 30 1234 5678"
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.EMPLOYER_PORTAL.value
    assert guidance.application_url is not None
    assert guidance.application_url.value == "https://jobs.example.de/apply/42"
    assert {item.value for item in guidance.requested_documents} == {
        "CV",
        "Cover letter",
        "Certificates",
    }
    assert guidance.max_file_size is not None
    assert guidance.max_file_size.value == "10 MB"
    assert guidance.max_pages is not None
    assert guidance.max_pages.value == "2"
    assert guidance.application_deadline is not None
    assert guidance.instructions
    assert all(item.provenance == GuidanceProvenance.ADVERTISEMENT for item in guidance.entries())
    assert all(item.evidence_quote and item.evidence_quote in source for item in guidance.entries())


def test_multiline_postal_application_address_is_kept_local_and_source_grounded() -> None:
    source = """Bitte senden Sie Ihre Bewerbung per Post an:
Example GmbH
Musterstraße 12
60311 Frankfurt am Main
Alternativ per E-Mail an jobs@example.de.
"""

    guidance = extract_application_guidance(source, source_url=URL)
    minimized = _minimize_job_text_for_provider(source)

    assert guidance.postal_address is not None
    assert guidance.postal_address.value == "Musterstraße 12, 60311 Frankfurt am Main"
    assert "Musterstraße 12" in guidance.postal_address.evidence_quote
    assert "60311 Frankfurt am Main" in guidance.postal_address.evidence_quote
    assert guidance.application_channel is not None
    assert guidance.application_channel.value == ApplicationChannel.POSTAL.value
    assert "Musterstraße 12" not in minimized
    assert "60311 Frankfurt am Main" not in minimized
    assert "[application contact retained locally]" in minimized


def test_multiline_german_and_french_contact_patterns_remain_source_grounded() -> None:
    multiline = """Kontaktperson:
Jonas Müller
Talent Acquisition Manager
Telefon: 069 / 123 45 678
"""
    german = extract_application_guidance(multiline, source_url=URL)

    assert german.contact_name is not None
    assert german.contact_name.value == "Jonas Müller"
    assert german.contact_role is not None
    assert german.contact_role.value == "Talent Acquisition Manager"
    assert german.contact_phone is not None
    assert german.contact_phone.value == "069 / 123 45 678"

    french_source = """Votre contact : Marie Dupont — Responsable recrutement
Envoyez votre candidature, votre CV et votre lettre de motivation par e-mail à recrutement@example.fr.
Date limite : 15 octobre 2026
"""
    french = extract_application_guidance(french_source, source_url=URL)

    assert french.contact_name is not None
    assert french.contact_name.value == "Marie Dupont"
    assert french.contact_role is not None
    assert french.contact_role.value == "Responsable recrutement"
    assert french.contact_email is not None
    assert french.contact_email.value == "recrutement@example.fr"
    assert french.application_channel is not None
    assert french.application_channel.value == ApplicationChannel.EMAIL.value
    assert {item.value for item in french.requested_documents} == {"CV", "Cover letter"}
    assert french.application_deadline is not None


def test_model_contact_value_cannot_claim_different_verbatim_evidence() -> None:
    source = "Contact person: Anna Example, Recruiting. Email: anna@example.eu"
    extraction = JobExtraction(
        title="Quality Engineer",
        company="Example GmbH",
        location="Berlin",
        summary="Quality engineering role.",
        facts=[],
        application_guidance=ApplicationGuidanceDraft(
            contact_name=ApplicationGuidanceEntryDraft(
                value="Invented Person",
                evidence_quote="Contact person: Anna Example, Recruiting",
            ),
            contact_email=ApplicationGuidanceEntryDraft(
                value="invented@example.eu",
                evidence_quote="Email: anna@example.eu",
            ),
        ),
    )

    with pytest.raises(UnverifiedEvidenceError) as error:
        extraction.to_job_posting(
            source_text=source,
            source_name=URL,
            source_url=URL,
            requested_url=URL,
            url_http_status=200,
            url_checked_at=NOW,
        )

    assert {issue.key for issue in error.value.issues} == {
        "application.contact_name",
        "application.contact_email",
    }


def test_job_extraction_prompt_keeps_contact_identity_local() -> None:
    source = """Quality Engineer at Example GmbH
Build and automate product-quality tests with Python.
Ansprechpartnerin: Frau Dr. Lena Weiß, Senior Recruiterin
Bitte per E-Mail an lena.weiss@example.de oder telefonisch +49 30 1234 5678 bewerben.
Details: https://jobs.example.de/apply/42
"""

    minimized = _minimize_job_text_for_provider(source)

    assert "Quality Engineer at Example GmbH" in minimized
    assert "Build and automate product-quality tests with Python" in minimized
    assert "Lena Weiß" not in minimized
    assert "Senior Recruiterin" not in minimized
    assert "lena.weiss@example.de" not in minimized
    assert "+49 30 1234 5678" not in minimized
    assert "https://jobs.example.de/apply/42" not in minimized
    assert "[application contact retained locally]" in minimized


def test_job_extraction_prompt_keeps_public_workplace_address_for_location_analysis() -> None:
    source = (
        "Test Engineer at Example GmbH. "
        "PostalAddress Deutschland Frankfurt am Main Hessen 60322 Nicht vorhanden. "
        "Build test automation with Python."
    )

    minimized = _minimize_job_text_for_provider(source)

    assert "60322" in minimized
    assert "Frankfurt am Main" in minimized


def test_job_extraction_prompt_removes_unusually_labelled_contact_sentence() -> None:
    source = (
        "Quality Engineer. Build test automation with Python. "
        "Please send your application to Jane Recruiter, Talent Acquisition Lead."
    )

    minimized = _minimize_job_text_for_provider(source)

    assert "Quality Engineer" in minimized
    assert "Build test automation with Python" in minimized
    assert "Jane Recruiter" not in minimized
    assert "Talent Acquisition Lead" not in minimized


@pytest.mark.parametrize(
    "private_sentence",
    (
        "For questions about your application, talk to Jane Doe, Talent Acquisition Lead.",
        "Questions about the application can be directed to Jane Doe, Head of Talent.",
        "Your recruiter will be Jane Doe from People Operations.",
        "Bewerbungskontakt: Lena Weiss, Talent Acquisition Lead.",
        "Hiring manager: Jane Doe, Engineering Director.",
        "Questions? Jane Doe, Senior Recruiter, is happy to help.",
        "Recruitment enquiries: Jane Doe, Talent Acquisition Lead.",
        "HR liaison — Jane Doe, People Partner.",
        "For application support ask Jane Doe from Talent Acquisition.",
        "For more details, Jane Doe (Talent Acquisition) is available.",
        "Further information: Jane Doe, Talent Acquisition Lead.",
        "Our recruitment lead is Jane Doe.",
        "The recruitment lead for this vacancy is Jane Doe.",
        "For further details, speak with Jane Doe, Senior Recruiter.",
    ),
)
def test_job_extraction_prompt_fails_closed_for_contact_shaped_sentences(
    private_sentence: str,
) -> None:
    minimized = _minimize_job_text_for_provider(
        f"Quality Engineer. Build test automation with Python. {private_sentence}"
    )

    assert "Build test automation with Python" in minimized
    assert "Jane Doe" not in minimized
    assert "Lena Weiss" not in minimized


@pytest.mark.parametrize(
    "public_job_text",
    (
        "Application Support Engineer. Maintain production systems and troubleshoot customer "
        "issues. Python required.",
        "Hiring Manager. Lead our recruiting team and improve hiring operations.",
        "Questions and experimentation drive our research engineering work. Build Python services.",
    ),
)
def test_job_extraction_prompt_preserves_occupational_contact_words(
    public_job_text: str,
) -> None:
    assert _minimize_job_text_for_provider(public_job_text) == public_job_text


def test_job_extraction_prompt_withholds_published_address_for_postal_delivery() -> None:
    source = (
        "Quality Engineer. Build test automation with Python. Apply by post. "
        "PostalAddress Deutschland Frankfurt am Main Hessen 60322 Nicht vorhanden."
    )

    minimized = _minimize_job_text_for_provider(source)

    assert "Build test automation with Python" in minimized
    assert "60322" not in minimized
    assert "Frankfurt am Main" not in minimized
