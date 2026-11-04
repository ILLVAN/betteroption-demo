from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from betteroption.container import ApplicationContainer
from betteroption.concurrency import CooperativeControlFlow
from betteroption.database import Database
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.job_overrides import JobEvidenceOverride, JobEvidenceOverrideKind
from betteroption.matching import (
    CONTEXT_SALARY_RANGE,
    MatchOutcome,
    _apply_salary_override,
    match_job,
)
from betteroption.llm import LLMTask, ModelRoute
from betteroption.operations import (
    ProviderBudgetPolicy,
    ProviderOperationLedger,
    ProviderOperationRow,
    RecordingSalaryBenchmarkProvider,
)
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.providers.openai_salary import (
    OpenAISalaryBenchmarkProvider,
    SalaryEvidenceDraft,
    SalaryResearchOutput,
)
from betteroption.salary import (
    SALARY_WEB_SEARCH_HOSTS,
    SalaryConfidence,
    SalaryEvidence,
    SalaryEstimateKind,
    SalaryGuess,
    SalaryPeriod,
    advertised_salary_present,
    estimate_salary,
    european_job_country,
    jobs_missing_advertised_salary,
)
from betteroption.settings import Settings
from betteroption.telemetry import ModelInvocationRow, SqlAlchemyInvocationRecorder


def _job(
    *,
    title: str = "Hairdresser",
    location: str = "Berlin, Germany",
    source_text: str = "Join our salon team in Berlin.",
    facts: list[JobFact] | None = None,
) -> JobPosting:
    return JobPosting(
        title=title,
        company="Example Employer",
        location=location,
        summary=f"Public summary for {title}.",
        source_type=JobSourceType.SAMPLE,
        source_name="sample",
        source_text=source_text,
        facts=facts or [],
    )


def _salary_profile() -> CandidateProfile:
    return CandidateProfile(
        facts=[
            ProfileFact(
                key="compensation.minimum",
                value="50000 EUR",
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.COMPENSATION_TIME,
                    text="At least 50000 EUR",
                ),
            )
        ]
    )


def _official_evidence(
    *,
    occupation: str = "Hairdressing occupations",
    country: str = "DE",
    region: str = "Germany",
    minimum: int = 30_000,
    maximum: int = 42_000,
    source_url: str = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907",
    confidence: SalaryConfidence = SalaryConfidence.LOW,
) -> SalaryEvidence:
    return SalaryEvidence(
        occupation_family=occupation,
        annual_min_eur=minimum,
        annual_max_eur=maximum,
        confidence=confidence,
        source_label="Official labour statistics",
        source_url=source_url,
        source_quote=f"{region}: {minimum} EUR to {maximum} EUR annual",
        mapping_explanation=f"The public title maps to {occupation}.",
        country_code=country,
        region=region,
        hours_basis="full-time",
        source_min_amount=minimum,
        source_max_amount=maximum,
        source_currency="EUR",
        source_period=SalaryPeriod.ANNUAL,
        periods_per_year=1,
        annualization_basis="The official source reports annual gross pay.",
    )


def test_private_salary_override_keeps_typed_evidence_for_serialization() -> None:
    override = JobEvidenceOverride(
        workspace_id=uuid4(),
        job_record_id=uuid4(),
        kind=JobEvidenceOverrideKind.CONTEXT,
        target_key=CONTEXT_SALARY_RANGE,
        target_label="Salary range",
        text_value="55000:70000",
    )

    estimate = _apply_salary_override(None, [override])

    assert estimate is not None
    assert estimate.evidence == ()
    assert estimate.model_dump(mode="json")["evidence"] == []


def test_non_engineering_job_uses_only_supplied_official_evidence() -> None:
    job = _job()

    estimate = estimate_salary(job, [_official_evidence()])

    assert estimate is not None
    assert estimate.occupation_family == "Hairdressing occupations"
    assert estimate.annual_min_eur == 30_000
    assert estimate.confidence == SalaryConfidence.LOW
    assert "not compensation advertised by this employer" in estimate.assumption


def test_missing_pay_abstains_without_attributable_research() -> None:
    assert estimate_salary(_job()) is None
    assert (
        estimate_salary(
            _job(),
            [
                _official_evidence(
                    source_url="https://salary-blog.example/hairdresser",
                )
            ],
        )
        is None
    )


def test_explicit_native_currency_pay_always_wins_but_a_benefit_budget_does_not() -> None:
    explicit = _job(
        location="Zurich, Switzerland",
        source_text="Salary: CHF 95,000 per year.",
    )
    extracted = _job(
        source_text="Competitive package.",
        facts=[
            JobFact(
                key="compensation.annual_gross",
                value="NOK 750000",
                kind=JobFactKind.OFFER,
                evidence_quote="Competitive package",
            )
        ],
    )
    benefit = _job(source_text="A €1,000 annual learning budget is available.")

    assert advertised_salary_present(explicit)
    assert advertised_salary_present(extracted)
    assert not advertised_salary_present(benefit)
    assert estimate_salary(explicit, [_official_evidence(country="CH")]) is None


@pytest.mark.parametrize(
    "text",
    (
        "Salary: 700000 Kč per year.",
        "Gross pay is 700000 kr per year.",
        "Salary: 120000 zł per year.",
        "Vergütung: 90000 CHF jährlich.",
    ),
)
def test_common_native_currency_salary_notation_suppresses_research(text: str) -> None:
    assert advertised_salary_present(_job(source_text=text))


def test_company_money_is_not_misread_as_candidate_salary() -> None:
    job = _job(source_text="Company revenue was €10 million last year. Salary is competitive.")
    assert not advertised_salary_present(job)


def test_non_salary_compensation_fact_does_not_suppress_research() -> None:
    job = _job(
        source_text="We offer a 1000 EUR learning budget.",
        facts=[
            JobFact(
                key="compensation.learning_budget",
                value="1000 EUR",
                kind=JobFactKind.OFFER,
                evidence_quote="1000 EUR learning budget",
            )
        ],
    )
    assert not advertised_salary_present(job)


def test_country_resolution_handles_remote_country_and_cross_country_locations() -> None:
    assert european_job_country(_job(location="Remote – France")) == "FR"
    assert european_job_country(_job(location="France")) == "FR"
    assert european_job_country(_job(location="Nicosia, Cyprus")) == "CY"
    assert european_job_country(_job(location="Paris / London")) is None
    assert european_job_country(_job(location="Austin, Texas, USA")) is None
    assert european_job_country(_job(location="Remote · Europe")) is None
    assert european_job_country(_job(location="Remote IT role")) is None


def test_german_evidence_is_never_applied_to_another_country() -> None:
    london = _job(title="Nurse", location="London, UK")
    assert estimate_salary(london, [_official_evidence()]) is None


def test_non_eur_evidence_requires_and_retains_attributable_ecb_conversion() -> None:
    london = _job(title="Nurse", location="London, UK")
    evidence = SalaryEvidence(
        occupation_family="Registered nurses",
        annual_min_eur=round(50_000 / 0.85),
        annual_max_eur=round(60_000 / 0.85),
        confidence=SalaryConfidence.LOW,
        source_label="National Careers Service",
        source_url="https://nationalcareers.service.gov.uk/job-profiles/nurse",
        source_quote="United Kingdom annual pay ranges from 50000 GBP to 60000 GBP.",
        mapping_explanation="The title directly maps to registered nurses.",
        country_code="GB",
        region="United Kingdom",
        hours_basis="full-time",
        source_min_amount=50_000,
        source_max_amount=60_000,
        source_currency="GBP",
        source_period=SalaryPeriod.ANNUAL,
        periods_per_year=1,
        annualization_basis="The official source reports annual gross pay.",
        exchange_rate_units_per_eur=0.85,
        exchange_rate_date=date(2026, 7, 31),
        exchange_source_url=(
            "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
            "euro_reference_exchange_rates/html/index.en.html"
        ),
        exchange_source_quote="On 31 July 2026, 1 EUR = 0.85 GBP.",
    )

    estimate = estimate_salary(london, [evidence])

    assert estimate is not None
    assert estimate.annual_min_eur == 58_824
    assert estimate.evidence[0].source_currency == "GBP"
    assert estimate.evidence[0].exchange_rate_date == date(2026, 7, 31)


def test_research_batch_requires_a_salary_criterion_and_is_bounded() -> None:
    jobs = [_job(title=f"Role {index}") for index in range(12)]
    no_salary_profile = CandidateProfile()

    assert jobs_missing_advertised_salary(no_salary_profile, jobs, limit=10) == []
    assert len(jobs_missing_advertised_salary(_salary_profile(), jobs, limit=10)) == 10


class _FakeResponses:
    def __init__(self, response: object) -> None:
        self.response = response
        self.kwargs: dict[str, object] = {}

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _FakeClient:
    def __init__(self, response: object) -> None:
        self.responses = _FakeResponses(response)


def _provider_response(drafts: list[SalaryEvidenceDraft], sources: list[str]) -> object:
    return SimpleNamespace(
        output_parsed=SalaryResearchOutput(evidence=drafts),
        output=[
            SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(sources=[SimpleNamespace(url=url) for url in sources]),
            )
        ],
        usage=None,
    )


def _german_draft(**updates) -> SalaryEvidenceDraft:
    values = dict(
        job_index=0,
        occupation_family="Hairdressing occupations",
        country_code="DE",
        region="Germany",
        hours_basis="full-time",
        confidence=SalaryConfidence.LOW,
        source_label="Bundesagentur für Arbeit Entgeltatlas",
        source_url="https://web.arbeitsagentur.de/entgeltatlas/beruf/9907?utm_source=test",
        source_quote=(
            "Hairdresser in Germany: full-time monthly lower quartile 2500 EUR and "
            "upper quartile 3500 EUR; 12 regular payments per year."
        ),
        mapping_explanation="The public title maps directly to hairdressing occupations.",
        source_min_amount=2_500,
        source_max_amount=3_500,
        source_currency="EUR",
        source_period=SalaryPeriod.MONTHLY,
        periods_per_year=12,
        annualization_basis="Twelve regular monthly values; special payments are excluded.",
    )
    values.update(updates)
    return SalaryEvidenceDraft(**values)


def test_openai_adapter_uses_one_bounded_restricted_call_and_validates_sources() -> None:
    consulted = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    response = _provider_response(
        [_german_draft(confidence=SalaryConfidence.MEDIUM)],
        [consulted],
    )
    client = _FakeClient(response)
    provider = OpenAISalaryBenchmarkProvider(client=client, max_tool_calls=7)
    job = _job()

    result = provider.research([job])

    assert result[job.id][0].annual_min_eur == 30_000
    assert result[job.id][0].confidence == SalaryConfidence.LOW
    assert result[job.id][0].source_url == consulted
    assert client.responses.kwargs["max_tool_calls"] == 7
    assert client.responses.kwargs["include"] == ["web_search_call.action.sources"]
    tool = client.responses.kwargs["tools"][0]
    assert tool["type"] == "web_search"
    assert tool["search_context_size"] == "low"
    assert tool["return_token_budget"] == "default"
    assert set(tool["filters"]["allowed_domains"]) == set(SALARY_WEB_SEARCH_HOSTS)
    sent = str(client.responses.kwargs["input"])
    assert "Hairdresser" in sent
    assert "50000 EUR" not in sent


def test_salary_prompt_withholds_contact_shaped_job_fields() -> None:
    consulted = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    response = _provider_response([_german_draft()], [consulted])
    client = _FakeClient(response)
    provider = OpenAISalaryBenchmarkProvider(client=client)
    job = _job().model_copy(
        update={
            "summary": (
                "Cut and style hair. For more details, Jane Doe (Talent Acquisition) "
                "is available at jane@example.eu. Switchboard +49 30 1234 5678."
            )
        }
    )

    provider.research([job])

    sent = str(client.responses.kwargs["input"])
    assert "Cut and style hair" in sent
    assert "Jane Doe" not in sent
    assert "jane@example.eu" not in sent
    assert "+49 30 1234 5678" not in sent


def test_adapter_rejects_unconsulted_or_unsupported_quotes_and_wrong_eures_country() -> None:
    official = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    unconsulted = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([_german_draft()], []))
    )
    unsupported = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(
            _provider_response(
                [_german_draft(source_quote="Germany salary table updated in 2025.")],
                [official],
            )
        )
    )
    wrong_country_url = (
        "https://eures.europa.eu/living-and-working/living-and-working-conditions-latvia_en"
    )
    wrong_country = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(
            _provider_response(
                [
                    _german_draft(
                        source_url=wrong_country_url,
                        source_label="EURES",
                        source_quote=(
                            "Hairdresser in Latvia: monthly lower pay 2500 EUR and "
                            "upper pay 3500 EUR."
                        ),
                    )
                ],
                [wrong_country_url],
            )
        )
    )
    job = _job()

    assert unconsulted.research([job]) == {}
    assert unsupported.research([job]) == {}
    assert wrong_country.research([job]) == {}


def test_adapter_rejects_an_occupation_source_without_title_linkage() -> None:
    source = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    draft = _german_draft(
        occupation_family="Registered nurses",
        source_quote=(
            "Registered nurses in Germany: full-time monthly lower 2500 EUR and "
            "upper 3500 EUR; 12 regular payments per year."
        ),
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [source]))
    )
    assert provider.research([_job(title="Hairdresser")]) == {}


@pytest.mark.parametrize(
    "draft",
    (
        _german_draft(
            source_quote=(
                "Hairdresser in Germany: full-time monthly lower 2500 EUR and upper 3500 EUR."
            )
        ),
        _german_draft(
            source_quote=(
                "Hairdresser in Germany: full-time monthly lower 2500 GBP and upper "
                "3500 GBP; "
                "12 regular payments per year."
            )
        ),
        _german_draft(
            source_quote=(
                "Hairdresser in Germany: full-time annual lower 2500 EUR and upper "
                "3500 EUR; "
                "12 regular payments per year."
            )
        ),
    ),
)
def test_adapter_rejects_unsupported_annualisation_currency_or_period(
    draft: SalaryEvidenceDraft,
) -> None:
    source = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [source]))
    )
    assert provider.research([_job()]) == {}


def test_adapter_does_not_let_model_authored_family_fake_source_linkage() -> None:
    source = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    draft = _german_draft(
        occupation_family="Hairdresser",
        source_quote=(
            "Germany full-time monthly lower 2500 EUR and upper 3500 EUR; "
            "12 regular payments per year."
        ),
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [source]))
    )

    assert provider.research([_job()]) == {}


@pytest.mark.parametrize(
    "unrelated_title",
    (
        "Full Stack Developer",
        "Annual Giving Manager",
        "National Account Manager",
        "Care Service Manager",
    ),
)
def test_generic_salary_words_do_not_fake_occupation_linkage(
    unrelated_title: str,
) -> None:
    source = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    draft = _german_draft(
        occupation_family="Registered nurses",
        source_quote=(
            "Registered nurses in Germany: full-time annual gross salary ranges from "
            "2500 EUR to 3500 EUR; one period per year."
        ),
        source_min_amount=2_500,
        source_max_amount=3_500,
        source_period=SalaryPeriod.ANNUAL,
        periods_per_year=1,
        annualization_basis="The official source reports annual gross pay.",
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [source]))
    )

    assert provider.research([_job(title=unrelated_title)]) == {}


def test_hourly_evidence_requires_weekly_hours_in_the_attributed_quote() -> None:
    source = "https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"
    draft = _german_draft(
        source_quote=(
            "Hairdresser in Germany: full-time hourly lower 20 EUR and upper 25 EUR; "
            "52 periods per year."
        ),
        source_min_amount=20,
        source_max_amount=25,
        source_period=SalaryPeriod.HOURLY,
        periods_per_year=52,
        weekly_hours_basis=40,
        annualization_basis="52 weeks and 40 hours per week.",
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [source]))
    )
    assert provider.research([_job()]) == {}


@pytest.mark.parametrize(
    "unsafe_url",
    (
        "https://attacker@web.arbeitsagentur.de/entgeltatlas/beruf/9907",
        "https://web.arbeitsagentur.de:444/entgeltatlas/beruf/9907",
    ),
)
def test_adapter_rejects_credentialed_or_nonstandard_port_sources(unsafe_url: str) -> None:
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(
            _provider_response(
                [_german_draft(source_url=unsafe_url)],
                [unsafe_url],
            )
        )
    )
    assert provider.research([_job()]) == {}


def test_adapter_rejects_non_eur_conversion_when_ecb_quote_does_not_bind_date() -> None:
    wage_url = "https://nationalcareers.service.gov.uk/job-profiles/nurse"
    ecb_url = (
        "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
        "euro_reference_exchange_rates/html/index.en.html"
    )
    draft = SalaryEvidenceDraft(
        job_index=0,
        occupation_family="Registered nurses",
        country_code="GB",
        region="United Kingdom",
        hours_basis="full-time",
        confidence=SalaryConfidence.LOW,
        source_label="National Careers Service",
        source_url=wage_url,
        source_quote=(
            "Nurse in the United Kingdom: full-time annual pay ranges from 50000 GBP to 60000 GBP."
        ),
        mapping_explanation="The public title maps directly to registered nurses.",
        source_min_amount=50_000,
        source_max_amount=60_000,
        source_currency="GBP",
        source_period=SalaryPeriod.ANNUAL,
        periods_per_year=1,
        annualization_basis="The source reports annual gross pay.",
        exchange_rate_units_per_eur=0.85,
        exchange_rate_date=date(2026, 7, 31),
        exchange_source_url=ecb_url,
        exchange_source_quote="In 2025, 1 EUR = 0.85 GBP.",
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [wage_url, ecb_url]))
    )

    assert provider.research([_job(title="Nurse", location="London, UK")]) == {}


def test_adapter_rejects_stale_ecb_conversion_even_when_attributed() -> None:
    wage_url = "https://nationalcareers.service.gov.uk/job-profiles/nurse"
    ecb_url = (
        "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/"
        "euro_reference_exchange_rates/html/index.en.html"
    )
    stale_date = datetime.now(timezone.utc).date() - timedelta(days=32)
    draft = SalaryEvidenceDraft(
        job_index=0,
        occupation_family="Registered nurses",
        country_code="GB",
        region="United Kingdom",
        hours_basis="full-time",
        confidence=SalaryConfidence.LOW,
        source_label="National Careers Service",
        source_url=wage_url,
        source_quote=(
            "Registered nurses in the United Kingdom: full-time annual pay ranges "
            "from 50000 GBP to 60000 GBP."
        ),
        mapping_explanation="The public title maps directly to registered nurses.",
        source_min_amount=50_000,
        source_max_amount=60_000,
        source_currency="GBP",
        source_period=SalaryPeriod.ANNUAL,
        periods_per_year=1,
        annualization_basis="The source reports annual gross pay.",
        exchange_rate_units_per_eur=0.85,
        exchange_rate_date=stale_date,
        exchange_source_url=ecb_url,
        exchange_source_quote=f"On {stale_date.isoformat()}, 1 EUR = 0.85 GBP.",
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [wage_url, ecb_url]))
    )

    assert provider.research([_job(title="Nurse", location="London, UK")]) == {}


def test_generic_eu_source_requires_country_inside_the_attributed_evidence() -> None:
    generic = "https://eures.europa.eu/living-and-working/index_en"
    draft = _german_draft(
        source_url=generic,
        source_label="EURES",
        source_quote=(
            "Hairdresser full-time monthly lower pay is 2500 EUR and upper pay is "
            "3500 EUR; "
            "12 regular payments per year."
        ),
    )
    provider = OpenAISalaryBenchmarkProvider(
        client=_FakeClient(_provider_response([draft], [generic]))
    )

    assert provider.research([_job()]) == {}


def test_match_reason_keeps_all_retained_salary_source_urls() -> None:
    job = _job()
    first = _official_evidence(confidence=SalaryConfidence.MEDIUM)
    second = _official_evidence(
        confidence=SalaryConfidence.MEDIUM,
        source_url="https://eures.europa.eu/living-and-working/germany_en",
    )

    result = match_job(_salary_profile(), job, salary_evidence=[first, second])

    reason = next(item for item in result.reasons if item.profile_key == "compensation.minimum")
    assert reason.outcome == MatchOutcome.UNKNOWN
    assert reason.evidence_urls == [first.source_url, second.source_url]
    assert "German benchmark" not in " ".join(reason.evidence_quotes)


def test_v071h_ai_salary_orientation_is_broad_unsourced_and_cautiously_supporting() -> None:
    job = _job(title="Museum educator", location="Berlin, Germany")
    profile = CandidateProfile(
        facts=[
            ProfileFact(
                key="compensation.annual_gross",
                value="45000 EUR",
                level=RequirementLevel.PREFERENCE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.COMPENSATION_TIME,
                    text="Around 45000 EUR",
                ),
            )
        ]
    )
    guess = SalaryGuess(
        occupation_family="Museum education",
        annual_min_eur=32_000,
        annual_max_eur=52_000,
        country_code="DE",
        region="Berlin",
        assumption="Broad 2026 full-time orientation inferred from role and region.",
    )

    automatic = match_job(profile, job)
    oriented = match_job(profile, job, salary_guess=guess)

    assert oriented.salary_estimate is not None
    assert oriented.salary_estimate.estimate_kind == SalaryEstimateKind.AI_ORIENTATION
    assert oriented.salary_estimate.source_url is None
    assert oriented.salary_estimate.confidence == SalaryConfidence.VERY_LOW
    assert oriented.score > automatic.score
    assert oriented.reasons[0].outcome == MatchOutcome.SUPPORTING
    assert oriented.reasons[0].evidence_urls == []
    assert "cannot prove a salary violation" in oriented.reasons[0].explanation


def test_v071h_ai_salary_orientation_resolves_missing_must_have_without_claiming_offer() -> None:
    job = _job(title="Museum educator", location="Berlin, Germany")
    salary_fact = ProfileFact(
        key="compensation.annual_gross",
        value="45000 EUR",
        level=RequirementLevel.MUST_HAVE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.COMPENSATION_TIME,
            text="At least 45000 EUR",
        ),
    )
    guess = SalaryGuess(
        occupation_family="Museum education",
        annual_min_eur=32_000,
        annual_max_eur=52_000,
        country_code="DE",
        region="Berlin",
        assumption="Broad 2026 full-time orientation inferred from role and region.",
    )

    automatic = match_job(CandidateProfile(facts=[salary_fact]), job)
    oriented = match_job(CandidateProfile(facts=[salary_fact]), job, salary_guess=guess)

    assert automatic.hard_evidence_coverage == 0
    assert oriented.hard_evidence_coverage == 100
    assert oriented.hard_violations == 0
    assert oriented.reasons[0].outcome == MatchOutcome.SUPPORTING
    assert oriented.score > automatic.score


class _Ledger:
    def __init__(self) -> None:
        self.operations = []

    def record(self, operation) -> None:
        self.operations.append(operation)


class _Budget:
    def allows(self, *, proposed_cost_usd=None) -> bool:
        return True


class _FixedSalaryProvider:
    name = "fixed-salary"

    def research(self, jobs):
        return {jobs[0].id: [_official_evidence()]}


def test_budget_wrapper_counts_one_batch_as_one_provider_operation() -> None:
    ledger = _Ledger()
    provider = RecordingSalaryBenchmarkProvider(
        _FixedSalaryProvider(),
        ledger,
        _Budget(),
        estimated_cost_usd=0.25,
    )

    result = provider.research([_job()])

    assert result
    assert len(ledger.operations) == 1
    assert ledger.operations[0].purpose == "salary-research"
    assert ledger.operations[0].unit_name == "batch"
    assert ledger.operations[0].estimated_cost_usd == 0.25


def _costed_salary_provider(
    database: Database,
    response: object,
    *,
    max_tool_calls: int = 2,
) -> tuple[OpenAISalaryBenchmarkProvider, _FakeClient]:
    client = _FakeClient(response)
    provider = OpenAISalaryBenchmarkProvider(
        route=ModelRoute(
            task=LLMTask.SALARY_RESEARCH,
            provider="openai",
            model="test-model",
            prompt_version="test",
            input_cost_per_million_usd=1,
            output_cost_per_million_usd=2,
        ),
        client=client,
        recorder=SqlAlchemyInvocationRecorder(database),
        max_tool_calls=max_tool_calls,
    )
    return provider, client


def test_combined_salary_ceiling_blocks_before_parse(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'salary-combined-block.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    response = _provider_response(
        [_german_draft()], ["https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"]
    )
    provider, client = _costed_salary_provider(database, response)
    jobs = [_job()]
    ceiling = provider.maximum_combined_cost_usd(
        jobs,
        tool_cost_per_call_usd=0.01,
    )
    prepared = provider._prepare_request(jobs)  # noqa: SLF001 - exact cost contract
    assert prepared is not None
    _, request_input = prepared
    expected_ceiling = round(
        (len(repr(request_input).encode("utf-8")) + 128_000) / 1_000_000
        + 5_000 * 2 / 1_000_000
        + 2 * 0.01,
        8,
    )
    assert ceiling == pytest.approx(expected_ceiling)
    assert ceiling is not None and ceiling > 0.025
    wrapped = RecordingSalaryBenchmarkProvider(
        provider,
        ledger,
        ProviderBudgetPolicy(ledger, daily_cost_limit_usd=0.025),
        estimated_cost_usd=0.02,
        tool_cost_per_call_usd=0.01,
    )

    assert wrapped.research(jobs) == {}
    assert client.responses.kwargs == {}
    with database.session_factory() as session:
        operation = session.scalar(select(ProviderOperationRow))
        invocation = session.scalar(select(ModelInvocationRow))
    assert operation is not None and operation.outcome == "blocked"
    assert invocation is None


def test_salary_success_records_one_combined_operation_uuid_and_actual_cost(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'salary-combined-success.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    response = _provider_response(
        [_german_draft()],
        ["https://web.arbeitsagentur.de/entgeltatlas/beruf/9907"],
    )
    response.usage = SimpleNamespace(input_tokens=20_000, output_tokens=50, total_tokens=20_050)
    provider, client = _costed_salary_provider(database, response)
    wrapped = RecordingSalaryBenchmarkProvider(
        provider,
        ledger,
        ProviderBudgetPolicy(ledger, daily_cost_limit_usd=1),
        estimated_cost_usd=0.02,
        tool_cost_per_call_usd=0.01,
    )

    result = wrapped.research([_job()])

    assert result
    with database.session_factory() as session:
        operations = list(session.scalars(select(ProviderOperationRow)).all())
        invocations = list(session.scalars(select(ModelInvocationRow)).all())
    assert len(operations) == 1
    assert len(invocations) == 1
    assert operations[0].id == invocations[0].id
    assert operations[0].outcome == "succeeded"
    prompt_only_ceiling = len(repr(client.responses.kwargs["input"]).encode("utf-8"))
    assert response.usage.input_tokens > prompt_only_ceiling
    assert operations[0].estimated_cost_usd == pytest.approx(0.0301)


class _ExplodingResponses:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("connection disappeared")


def test_unknown_salary_outcome_keeps_combined_maximum_without_duplicate(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'salary-combined-unknown.db').as_posix()}")
    ledger = ProviderOperationLedger(database)
    client = SimpleNamespace(responses=_ExplodingResponses())
    provider = OpenAISalaryBenchmarkProvider(
        route=ModelRoute(
            task=LLMTask.SALARY_RESEARCH,
            provider="openai",
            model="test-model",
            prompt_version="test",
            input_cost_per_million_usd=1,
            output_cost_per_million_usd=2,
        ),
        client=client,
        recorder=SqlAlchemyInvocationRecorder(database),
        max_tool_calls=2,
    )
    ceiling = provider.maximum_combined_cost_usd(
        [_job()],
        tool_cost_per_call_usd=0.01,
    )
    assert ceiling is not None
    wrapped = RecordingSalaryBenchmarkProvider(
        provider,
        ledger,
        ProviderBudgetPolicy(ledger, daily_cost_limit_usd=1),
        estimated_cost_usd=0.02,
        tool_cost_per_call_usd=0.01,
    )

    assert wrapped.research([_job()]) == {}
    assert client.responses.calls == 1
    with database.session_factory() as session:
        operations = list(session.scalars(select(ProviderOperationRow)).all())
        invocations = list(session.scalars(select(ModelInvocationRow)).all())
    assert len(operations) == 1
    assert len(invocations) == 1
    assert operations[0].id == invocations[0].id
    assert operations[0].outcome == "failed"
    assert operations[0].estimated_cost_usd == pytest.approx(ceiling)


def test_cooperative_salary_abort_keeps_combined_maximum(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'salary-combined-cancel.db').as_posix()}")
    ledger = ProviderOperationLedger(database)

    class CancelledResponses:
        def parse(self, **_kwargs):
            raise CooperativeControlFlow

    provider = OpenAISalaryBenchmarkProvider(
        route=ModelRoute(
            task=LLMTask.SALARY_RESEARCH,
            provider="openai",
            model="test-model",
            prompt_version="test",
            input_cost_per_million_usd=1,
            output_cost_per_million_usd=2,
        ),
        client=SimpleNamespace(responses=CancelledResponses()),
        recorder=SqlAlchemyInvocationRecorder(database),
        max_tool_calls=2,
    )
    ceiling = provider.maximum_combined_cost_usd(
        [_job()],
        tool_cost_per_call_usd=0.01,
    )
    assert ceiling is not None
    wrapped = RecordingSalaryBenchmarkProvider(
        provider,
        ledger,
        ProviderBudgetPolicy(ledger, daily_cost_limit_usd=1),
        estimated_cost_usd=0.02,
        tool_cost_per_call_usd=0.01,
    )

    with pytest.raises(CooperativeControlFlow):
        wrapped.research([_job()])

    with database.session_factory() as session:
        operations = list(session.scalars(select(ProviderOperationRow)).all())
        invocations = list(session.scalars(select(ModelInvocationRow)).all())
    assert len(operations) == 1
    assert invocations == []
    assert operations[0].outcome == "failed"
    assert operations[0].estimated_cost_usd == pytest.approx(ceiling)


def test_container_reserves_the_configured_maximum_web_search_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "betteroption.providers.openai_salary.OpenAI",
        lambda **_kwargs: SimpleNamespace(),
    )
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'salary-cost.db').as_posix()}",
            openai_api_key="test-key",
            salary_research_enabled=True,
            salary_research_max_tool_calls=4,
            salary_research_estimated_cost_per_call_usd=0.25,
            _env_file=None,
        )
    )

    provider = container.salary_benchmark_provider()

    assert isinstance(provider, RecordingSalaryBenchmarkProvider)
    assert provider.estimated_cost_usd == 1.0
    assert provider.tool_cost_per_call_usd == 0.25
    assert provider.provider.search_content_token_ceiling == 128_000


def test_salary_search_content_ceiling_setting_defaults_and_overrides() -> None:
    assert Settings(_env_file=None).salary_research_search_content_token_ceiling == 128_000
    with pytest.raises(ValueError):
        Settings(
            BETTEROPTION_SALARY_RESEARCH_SEARCH_CONTENT_TOKEN_CEILING=127_999,
            _env_file=None,
        )
    assert (
        Settings(
            BETTEROPTION_SALARY_RESEARCH_SEARCH_CONTENT_TOKEN_CEILING=256_000,
            _env_file=None,
        ).salary_research_search_content_token_ceiling
        == 256_000
    )


def test_salary_provider_defensively_clamps_search_content_ceiling() -> None:
    provider = OpenAISalaryBenchmarkProvider(
        client=SimpleNamespace(),
        search_content_token_ceiling=127_999,
    )
    safely_raised = OpenAISalaryBenchmarkProvider(
        client=SimpleNamespace(),
        search_content_token_ceiling=256_000,
    )

    assert provider.search_content_token_ceiling == 128_000
    assert safely_raised.search_content_token_ceiling == 256_000
