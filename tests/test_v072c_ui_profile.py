from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.jobs import JobFact, JobFactKind, JobPosting, JobSourceType
from betteroption.matching import MatchOutcome, match_job
from betteroption.profile import (
    SUPPORTED_COMPENSATION_CURRENCIES,
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
)
from betteroption.salary import SalaryGuess
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.web import create_app


ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "src/betteroption/web/templates"
STATIC = ROOT / "src/betteroption/web/static"


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'v072c-ui.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
        )
    )


def test_explore_distance_slider_is_persistent_and_does_not_filter_remote_roles() -> None:
    template = (TEMPLATES / "explore.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "data-max-distance-filter" in template
    assert 'min="0" max="40" step="1" value="21"' in template
    assert (
        'data-distance-stops="5,10,15,20,25,30,35,40,45,50,55,60,65,70,75,80,'
        "85,90,95,100,125,150,175,200,225,250,275,300,325,350,375,400,425,450,"
        '475,500,600,700,800,900,1000"'
    ) in template
    slider_tag = template.split('id="explore-max-distance"', 1)[1].split(">", 1)[0]
    assert "name=" not in slider_tag
    assert "Remote roles and unresolved locations stay available." in template
    assert (
        "data-distance-km=\"{{ job.distance_km if job.distance_km is not none else '' }}\""
        in template
    )
    assert "betteroption:explore:max-distance-km" in javascript
    assert "const distanceStops" in javascript
    assert "nearestDistanceIndex" in javascript
    assert "const maximumDistance = distanceAtSlider();" in javascript
    assert 'searchParams.set("max_distance_km"' in javascript
    assert "!isRemoteOnly" in javascript
    assert "Number.isFinite(distance)" in javascript
    assert "distance > maximumDistance" in javascript
    assert (
        'distanceLabel = distanceIsBounded ? `${maximumDistance} km` : "Any distance"' in javascript
    )


def test_explore_card_uses_metadata_then_a_serif_title_without_tight_employer_cap() -> None:
    template = (TEMPLATES / "explore.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    metadata = template.index('class="explore-result-meta"')
    title = template.index('class="explore-result-title"')
    assert metadata < title
    metadata_markup = template[metadata:title]
    assert 'class="explore-selector"' in metadata_markup
    assert 'class="discovery-source"' not in metadata_markup
    assert 'class="company" title="{{ job.company }}"' in metadata_markup
    assert 'class="location" title=' in metadata_markup
    assert template.index('class="explore-provider-badge"') > title
    title_rule = css.split(".explore-result-title {", 1)[1].split("}", 1)[0]
    assert "font-family: Georgia, serif;" in title_rule
    assert "max-width: 22rem" not in css
    employer_rule = css.split(".explore-result-meta .company {", 1)[1].split("}", 1)[0]
    assert "white-space: normal;" in employer_rule
    assert "text-overflow: clip;" in employer_rule


def test_currency_selector_defaults_legacy_profiles_to_eur_and_persists_iso_currency(
    tmp_path: Path,
) -> None:
    assert 20 <= len(SUPPORTED_COMPENSATION_CURRENCIES) <= 50
    assert {
        "EUR",
        "GBP",
        "CHF",
        "NOK",
        "PLN",
        "UAH",
        "USD",
        "JPY",
        "CNY",
    }.issubset(SUPPORTED_COMPENSATION_CURRENCIES)
    assert CandidateProfile.model_validate({"compensation": {}}).compensation.currency == "EUR"

    container = _container(tmp_path)
    workspace = container.workspaces.create(new_session())
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))
    page = client.get(f"/profile/{workspace.id}")
    soup = BeautifulSoup(page.text, "html.parser")
    selector = soup.select_one('select[name="currency"][aria-label="Salary currency"]')
    assert selector is not None
    assert selector.select_one('option[value="EUR"][selected]') is not None
    assert len(selector.select("option")) == len(SUPPORTED_COMPENSATION_CURRENCIES)

    response = client.post(
        f"/profile/{workspace.id}/compensation-range",
        data={
            "currency": "CHF",
            "minimum_gross_annual": "65000",
            "target_gross_annual": "80000",
        },
        follow_redirects=False,
    )
    saved = container.workspaces.get(workspace.id)
    assert response.status_code == 303
    assert saved is not None
    assert saved.session.profile.compensation.currency == "CHF"
    assert {
        str(fact.value)
        for fact in saved.session.profile.confirmed_facts
        if fact.key == "compensation.annual_gross"
    } == {"CHF 65000", "CHF 80000"}

    invalid = client.post(
        f"/profile/{workspace.id}/compensation-range",
        data={
            "currency": "XYZ",
            "minimum_gross_annual": "65000",
            "target_gross_annual": "80000",
        },
        follow_redirects=False,
    )
    unchanged = container.workspaces.get(workspace.id)
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]
    assert unchanged is not None and unchanged.session.profile.compensation.currency == "CHF"


def test_programming_language_tile_is_visually_subordinate_but_keeps_its_form() -> None:
    template = (TEMPLATES / "profile_compass.html").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    assert 'details class="v072-language-tile v072-programming-language-tile"' in template
    assert "profile_programming_languages" in template
    assert ".v072-programming-language-tile {" in css
    rule = css.split(".v072-programming-language-tile {", 1)[1].split("}", 1)[0]
    assert "padding: 0.62rem 0.78rem;" in rule
    assert "background: rgba(255, 255, 255, 0.38);" in rule
    assert ".v072-programming-language-tile[open]" in css


def _salary_profile(currency: str) -> CandidateProfile:
    return CandidateProfile(
        facts=[
            ProfileFact(
                key="compensation.annual_gross",
                value=f"{currency} 65000",
                level=RequirementLevel.MUST_HAVE,
                evidence_status=EvidenceStatus.CONFIRMED,
                confidence=Confidence.HIGH,
                source=SourceExcerpt(
                    section=ProfileSection.COMPENSATION_TIME,
                    text=f"Minimum {currency} 65000 gross per year.",
                ),
            )
        ]
    )


def _salary_job(value: str) -> JobPosting:
    return JobPosting(
        title="Engineer",
        company="Example",
        location="Zurich, Switzerland",
        summary="Build products.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text=f"Annual salary: {value}.",
        facts=[
            JobFact(
                key="compensation.annual_gross",
                value=value,
                kind=JobFactKind.OFFER,
                evidence_quote=f"Annual salary: {value}.",
            )
        ],
    )


def test_salary_matching_abstains_across_currencies_but_compares_matching_codes() -> None:
    different = match_job(_salary_profile("CHF"), _salary_job("EUR 100000"))
    same = match_job(_salary_profile("CHF"), _salary_job("CHF 70000"))

    different_reason = next(
        reason for reason in different.reasons if reason.profile_key == "compensation.annual_gross"
    )
    same_reason = next(
        reason for reason in same.reasons if reason.profile_key == "compensation.annual_gross"
    )
    assert different_reason.outcome == MatchOutcome.UNKNOWN
    assert different.hard_violations == 0
    assert same_reason.outcome == MatchOutcome.SATISFIED

    legacy = _salary_profile("EUR")
    legacy.facts[0].value = "65000 all in"
    ordinary_word = match_job(legacy, _salary_job("EUR 70000"))
    ordinary_reason = next(
        reason
        for reason in ordinary_word.reasons
        if reason.profile_key == "compensation.annual_gross"
    )
    assert ordinary_reason.outcome == MatchOutcome.SATISFIED


def test_non_eur_compass_amount_is_not_compared_to_eur_salary_orientation() -> None:
    profile = _salary_profile("CHF")
    job = JobPosting(
        title="Engineer",
        company="Example",
        location="Zurich, Switzerland",
        summary="Build products.",
        source_type=JobSourceType.SAMPLE,
        source_name="test",
        source_text="Competitive salary.",
    )
    result = match_job(
        profile,
        job,
        salary_guess=SalaryGuess(
            occupation_family="Engineering",
            annual_min_eur=70_000,
            annual_max_eur=90_000,
            country_code="CH",
            region="Zurich",
            assumption="Broad EUR-normalized orientation.",
        ),
    )

    reason = next(
        item for item in result.reasons if item.profile_key == "compensation.annual_gross"
    )
    assert reason.outcome == MatchOutcome.UNKNOWN
    assert "does not apply an unstated or static exchange rate" in reason.explanation
