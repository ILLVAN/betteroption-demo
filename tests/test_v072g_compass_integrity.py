from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote_plus
from uuid import uuid4

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
import pytest

from betteroption.candidate_languages import (
    PracticalProficiency,
    profile_language_mentions,
    profile_language_selections,
)
from betteroption.container import ApplicationContainer
from betteroption.discovery import DiscoveryQuery, discovery_query_from_profile
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    LocationPreference,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    ReviewAction,
    SourceExcerpt,
)
from betteroption.profile_integrity import (
    CompassAction,
    CompassIntegritySeverity,
    inspect_compass_integrity,
)
from betteroption.profile_mobility import mobility_widget_preferences
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.session import SectionStatus, new_session
from betteroption.settings import Settings
from betteroption.web import create_app


def _fact(
    key: str,
    value: str,
    level: RequirementLevel = RequirementLevel.PREFERENCE,
    section: ProfileSection = ProfileSection.DIRECTION,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(section=section, text=value),
    )


def _contradictory_session():
    session = new_session()
    session.profile.facts = [
        _fact("industry.sector", "defence", RequirementLevel.MUST_HAVE),
        _fact(
            "industry.sector",
            "defence",
            RequirementLevel.EXCLUSION,
            ProfileSection.EXCLUSIONS,
        ),
    ]
    return session


class _RecordingDiscovery:
    name = "recording"
    attribution = "Recording source"
    attribution_url = "https://example.com/source"

    def __init__(self) -> None:
        self.queries: list[DiscoveryQuery] = []

    def search(self, query: DiscoveryQuery) -> list:
        self.queries.append(query)
        return []


def _web_fixture(tmp_path: Path):
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'integrity.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            employer_homepage_research=False,
        )
    )
    workspace = container.workspaces.create(_contradictory_session())
    discovery = _RecordingDiscovery()
    client = TestClient(
        create_app(
            container,
            data_directory=tmp_path / "data",
            discovery_provider=discovery,
        )
    )
    return container, workspace, discovery, client


def test_integrity_report_blocks_only_actions_that_consume_the_whole_compass() -> None:
    report = inspect_compass_integrity(_contradictory_session())

    assert not report.allows(CompassAction.EXPLORE_COMPASS)
    assert not report.allows(CompassAction.MATCH)
    assert not report.allows(CompassAction.APPLY_NEW)
    assert report.allows(CompassAction.ADD)
    assert report.allows(CompassAction.EXPLORE_MANUAL)
    assert report.allows(CompassAction.ARCHIVE)
    issue = report.primary_issue(CompassAction.MATCH)
    assert issue is not None
    assert issue.severity == CompassIntegritySeverity.BLOCKING
    assert issue.code == "opposite-level:industry.sector"


@pytest.mark.parametrize(
    ("maximum", "minimum"),
    [
        ("At most 2 days per week in the office", "At least 4 days per week in the office"),
        ("Höchstens 2 Tage pro Woche im Büro", "Mindestens 4 Tage pro Woche im Büro"),
        ("2", "4"),
    ],
)
def test_incompatible_numeric_must_have_boundaries_block_compass_consumers(
    maximum: str,
    minimum: str,
) -> None:
    session = new_session()
    session.profile.facts = [
        _fact("role.family", "product engineering"),
        _fact(
            "work_model.office_days_max",
            maximum,
            RequirementLevel.MUST_HAVE,
            ProfileSection.WORKING_MODEL,
        ),
        _fact(
            "work_model.office_days_min",
            minimum,
            RequirementLevel.MUST_HAVE,
            ProfileSection.WORKING_MODEL,
        ),
    ]

    report = inspect_compass_integrity(session)
    issue = next(item for item in report.issues if item.code.startswith("incompatible-bounds:"))

    assert issue.severity == CompassIntegritySeverity.BLOCKING
    assert not report.allows(CompassAction.EXPLORE_COMPASS)
    assert not report.allows(CompassAction.MATCH)
    assert not report.allows(CompassAction.APPLY_NEW)
    assert report.allows(CompassAction.ADD)


def test_numeric_preferences_can_be_broad_without_becoming_a_hard_gate() -> None:
    session = new_session()
    session.profile.facts = [
        _fact("role.family", "product engineering"),
        _fact("work_model.office_days_max", "at most 2", RequirementLevel.PREFERENCE),
        _fact("work_model.office_days_min", "at least 4", RequirementLevel.PREFERENCE),
    ]

    report = inspect_compass_integrity(session)

    assert not any(issue.code.startswith("incompatible-bounds:") for issue in report.issues)
    assert report.allows(CompassAction.MATCH)


@pytest.mark.parametrize(
    "wording",
    [
        "I do not want fully remote work",
        "Ich möchte nicht vollständig remote arbeiten",
    ],
)
def test_negated_remote_wording_never_becomes_a_remote_must_have(wording: str) -> None:
    session = new_session()
    session.profile.facts = [
        _fact("role.family", "product engineering"),
        _fact(
            "work_model.remote_only",
            wording,
            RequirementLevel.MUST_HAVE,
            ProfileSection.WORKING_MODEL,
        ),
        _fact(
            "work_model.onsite_only",
            "onsite only",
            RequirementLevel.MUST_HAVE,
            ProfileSection.WORKING_MODEL,
        ),
    ]

    report = inspect_compass_integrity(session)
    assert not any(issue.code == "workplace-extremes" for issue in report.issues)
    assert report.allows(CompassAction.MATCH)


def test_broad_directions_suggest_a_second_persona_without_blocking() -> None:
    session = new_session()
    session.profile.facts = [
        _fact("role.family", "software engineering"),
        _fact("seniority.target", "senior", RequirementLevel.MUST_HAVE),
        _fact("role.level", "junior role", RequirementLevel.PREFERENCE),
    ]

    report = inspect_compass_integrity(session)
    issue = next(item for item in report.issues if item.code == "seniority-extremes")

    assert issue.severity == CompassIntegritySeverity.WARNING
    assert issue.suggest_second_persona
    assert all(report.allows(action) for action in CompassAction)


def test_compass_explore_needs_direction_but_manual_explore_stays_available() -> None:
    session = new_session()
    session.profile.facts = [_fact("work_model.remote", "hybrid is acceptable")]

    report = inspect_compass_integrity(session)

    assert not report.allows(CompassAction.EXPLORE_COMPASS)
    assert report.allows(CompassAction.EXPLORE_MANUAL)
    assert report.allows(CompassAction.MATCH)
    assert report.allows(CompassAction.APPLY_NEW)


def test_ask_me_later_is_an_informational_open_point_not_a_persisted_bypass() -> None:
    session = new_session()
    session.profile.facts = [_fact("role.family", "product engineering")]
    session.sections[0].status = SectionStatus.SKIPPED

    report = inspect_compass_integrity(session)
    issue = next(item for item in report.issues if item.code == "guided-points-open")

    assert issue.severity == CompassIntegritySeverity.INFO
    assert "Only confirmed statements" in issue.explanation
    assert "Ask me later" not in issue.explanation
    assert not issue.blocked_actions
    assert all(report.allows(action) for action in CompassAction)


def test_all_story_pages_share_the_action_aware_compass_notice(tmp_path: Path) -> None:
    _container, _workspace, _discovery, client = _web_fixture(tmp_path)
    blocked_pages = {"/explore", "/matches", "/apply"}

    for path in ("/add", "/explore", "/matches", "/apply", "/jobs"):
        response = client.get(path)
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        notice = soup.select_one("#compass-integrity-notice")
        assert notice is not None
        assert "The same condition is both wanted and excluded" in notice.get_text(" ")
        assert notice.select_one("[data-compass-integrity-dismiss]") is None
        assert ("is-blocking-here" in notice.get("class", [])) is (path in blocked_pages)


def test_server_gates_cannot_be_bypassed_but_manual_explore_still_runs(
    tmp_path: Path,
) -> None:
    _container, _workspace, discovery, client = _web_fixture(tmp_path)

    compass_search = client.post(
        "/explore/search",
        data={"use_compass": "true"},
        follow_redirects=False,
    )
    manual_search = client.post(
        "/explore/search",
        data={"q": "embedded software"},
        follow_redirects=False,
    )
    matching = client.post(
        "/matches/run",
        data={"confirm_consistency": "true"},
        follow_redirects=False,
    )
    apply_generation = client.post(
        "/apply/generate",
        data={},
        follow_redirects=False,
    )
    apply_transform = client.post(
        f"/apply/{uuid4()}/transform",
        data={"action": "shorter", "confirm_ai_processing": "true"},
        follow_redirects=False,
    )

    assert compass_search.status_code == 303
    assert (
        "same condition is both wanted and excluded"
        in unquote_plus(compass_search.headers["location"]).casefold()
    )
    assert manual_search.status_code == 303
    assert len(discovery.queries) == 1
    assert discovery.queries[0].text == "embedded software"
    assert (
        "same condition is both wanted and excluded"
        in unquote_plus(matching.headers["location"]).casefold()
    )
    assert (
        "same condition is both wanted and excluded"
        in unquote_plus(apply_generation.headers["location"]).casefold()
    )
    assert (
        "same condition is both wanted and excluded"
        in unquote_plus(apply_transform.headers["location"]).casefold()
    )


def test_mobility_edits_update_widget_legacy_projection_and_explore_query(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'mobility-sync.db').as_posix()}",
            auth_mode="local",
        )
    )
    session = new_session()
    origin = _fact(
        "location.origin",
        "Frankfurt",
        RequirementLevel.OPEN,
        ProfileSection.LOCATION_MOBILITY,
    )
    session.profile.facts = [_fact("role.family", "embedded engineering"), origin]
    session.profile.location = LocationPreference(origin_label="Stale typed location")
    workspace = container.workspaces.create(session)
    service = ProfileWorkflowService(container.workspaces)

    edited = service.revise_confirmed_fact(
        workspace.id,
        origin.id,
        action=ReviewAction.EDIT_VALUE,
        new_value="München Hauptbahnhof",
    )

    assert edited.session.profile.location is not None
    assert edited.session.profile.location.origin_label == "München Hauptbahnhof"
    assert (
        mobility_widget_preferences(edited.session.profile).origin_label == "München Hauptbahnhof"
    )
    assert discovery_query_from_profile(edited.session.profile).location == "München Hauptbahnhof"

    cleared = service.revise_confirmed_fact(
        workspace.id,
        origin.id,
        action=ReviewAction.REJECT,
    )
    assert cleared.session.profile.location is None
    assert mobility_widget_preferences(cleared.session.profile).origin_label == ""
    assert discovery_query_from_profile(cleared.session.profile).location == ""


def test_guided_and_cv_languages_hydrate_widgets_without_inventing_levels(
    tmp_path: Path,
) -> None:
    spoken = _fact(
        "language.spoken",
        "German C1",
        RequirementLevel.OPEN,
        ProfileSection.EXPERIENCE,
    )
    programming_mention = _fact(
        "experience.summary",
        "Built services with Python",
        RequirementLevel.OPEN,
        ProfileSection.EXPERIENCE,
    )
    profile = CandidateProfile(facts=[spoken, programming_mention])

    assert profile_language_selections(profile, programming=False) == {
        "German": PracticalProficiency.PROFESSIONAL
    }
    assert profile_language_selections(profile, programming=True) == {}
    assert "Python" in profile_language_mentions(profile, programming=True)

    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'language-sync.db').as_posix()}",
            auth_mode="local",
        )
    )
    session = new_session()
    session.profile = profile
    workspace = container.workspaces.create(session)
    saved = ProfileWorkflowService(container.workspaces).save_candidate_languages(
        workspace.id,
        names=["German"],
        proficiencies=[PracticalProficiency.NATIVE.value],
        programming=False,
    )

    replaced = next(fact for fact in saved.session.profile.facts if fact.id == spoken.id)
    assert replaced.evidence_status == EvidenceStatus.REJECTED
    stored_spoken = [
        fact
        for fact in saved.session.profile.facts
        if fact.key == "language.spoken" and fact.evidence_status == EvidenceStatus.CONFIRMED
    ]
    assert [fact.value for fact in stored_spoken] == ["German · native"]
    assert profile_language_selections(saved.session.profile, programming=False) == {
        "German": PracticalProficiency.NATIVE
    }


def test_editing_a_numeric_compensation_fact_to_negotiable_clears_typed_range(
    tmp_path: Path,
) -> None:
    container = ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'compensation-sync.db').as_posix()}",
            auth_mode="local",
        )
    )
    session = new_session()
    salary = ProfileFact(
        key="compensation.minimum",
        value="EUR 65,000",
        level=RequirementLevel.MUST_HAVE,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.COMPENSATION_TIME,
            text="My minimum is EUR 65,000 gross per year.",
        ),
    )
    session.profile.facts = [_fact("role.family", "product engineering"), salary]
    session.profile.compensation.minimum_gross_annual = 65_000
    session.profile.compensation.target_gross_annual = 75_000
    workspace = container.workspaces.create(session)

    saved = ProfileWorkflowService(container.workspaces).revise_confirmed_fact(
        workspace.id,
        salary.id,
        action=ReviewAction.EDIT_VALUE,
        new_value="Negotiable",
    )

    assert saved.session.profile.compensation.minimum_gross_annual is None
    assert saved.session.profile.compensation.target_gross_annual is None


def test_guided_setup_is_primary_and_restart_stays_in_the_centered_side_tile() -> None:
    project_root = Path(__file__).parents[1]
    compass_template = (
        project_root / "src/betteroption/web/templates/profile_compass.html"
    ).read_text(encoding="utf-8")
    conversation_template = (
        project_root / "src/betteroption/web/templates/profile_conversation.html"
    ).read_text(encoding="utf-8")
    css = (project_root / "src/betteroption/web/static/app.css").read_text(encoding="utf-8")
    script = (project_root / "src/betteroption/web/static/app.js").read_text(encoding="utf-8")

    assert compass_template.index("Guided setup") < compass_template.index("Add a job")
    assert compass_template.index("Add a job") < compass_template.index("Explore jobs")
    assert compass_template.index("Explore jobs") < compass_template.index("Open Matching")
    sidebar = BeautifulSoup(conversation_template, "html.parser").select_one(".guided-sidebar-card")
    assert sidebar is not None
    assert "Start a new compass" in sidebar.get_text(" ")
    assert conversation_template.count("Start a new compass") == 1
    sidebar_rule = css.split(".guided-sidebar {", 1)[1].split("}", 1)[0]
    card_rule = css.split(".guided-sidebar-card {", 1)[1].split("}", 1)[0]
    assert "top: 50vh" not in sidebar_rule
    assert "position: fixed" in card_rule
    assert "top: 50vh" in card_rule
    assert "transform: translateY(-50%)" in card_rule
    assert "min-height: 12rem" in css
    apply_template = (project_root / "src/betteroption/web/templates/apply.html").read_text(
        encoding="utf-8"
    )
    for action in ("shorter", "longer", "recreate"):
        button = apply_template.split(f'value="{action}"', 1)[1].split(">", 1)[0]
        assert "application_generation_allowed" in button
        assert "disabled" in button
    assert 'document.querySelectorAll("[data-compass-integrity-dismiss]")' not in script
    assert "Ask me later" in conversation_template
