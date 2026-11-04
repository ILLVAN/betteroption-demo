from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.container import ApplicationContainer
from betteroption.profile import (
    CandidateProfile,
    Confidence,
    EvidenceStatus,
    LocationPreference,
    ProfileFact,
    ProfileSection,
    RequirementLevel,
    SourceExcerpt,
    TravelConstraint,
    TravelMode,
)
from betteroption.profile_mobility import mobility_widget_preferences
from betteroption.profile_workflow import ProfileWorkflowService
from betteroption.session import new_session
from betteroption.settings import Settings
from betteroption.web import create_app


def _fact(
    key: str,
    value: str,
    level: RequirementLevel = RequirementLevel.PREFERENCE,
) -> ProfileFact:
    return ProfileFact(
        key=key,
        value=value,
        level=level,
        evidence_status=EvidenceStatus.CONFIRMED,
        confidence=Confidence.HIGH,
        source=SourceExcerpt(
            section=ProfileSection.LOCATION_MOBILITY,
            text=value,
        ),
    )


def _container(tmp_path: Path) -> ApplicationContainer:
    return ApplicationContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'mobility-widget.db').as_posix()}",
            auth_mode="local",
            background_worker_enabled=False,
            osm_geocoder_enabled=False,
        )
    )


def test_guided_facts_hydrate_the_compact_mobility_widget() -> None:
    profile = CandidateProfile(
        location=LocationPreference(
            origin_label="Legacy city fallback",
            travel_constraints=[
                TravelConstraint(
                    mode=TravelMode.BICYCLE,
                    maximum_minutes_one_way=25,
                )
            ],
        ),
        facts=[
            _fact("location.origin", "München Hauptbahnhof", RequirementLevel.OPEN),
            _fact("commute.transit.max_minutes", "60 minutes by transit one way"),
            _fact(
                "commute.car.max_minutes",
                "45 minutes by car one way",
                RequirementLevel.MUST_HAVE,
            ),
        ],
    )

    preferences = mobility_widget_preferences(profile)

    assert preferences.origin_label == "München Hauptbahnhof"
    assert preferences.transit_minutes == 60
    assert preferences.car_minutes == 45
    assert preferences.bicycle_minutes == 25
    assert preferences.is_active


def test_saving_the_widget_is_atomic_neutral_and_preserves_guided_levels(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create(new_session())
    workspace.session.profile.location = LocationPreference(
        origin_label="München",
        travel_constraints=[
            TravelConstraint(
                mode=TravelMode.WALK,
                maximum_minutes_one_way=15,
                level=RequirementLevel.PREFERENCE,
            )
        ],
    )
    workspace.session.profile.facts.extend(
        [
            _fact("location.origin", "München", RequirementLevel.OPEN),
            _fact(
                "commute.transit.max_minutes",
                "60 minutes by transit one way",
                RequirementLevel.MUST_HAVE,
            ),
            _fact("commute.walk.max_minutes", "15 minutes by walk one way"),
        ]
    )
    container.workspaces.save(workspace)
    service = ProfileWorkflowService(container.workspaces)

    saved = service.save_mobility_preferences(
        workspace.id,
        origin_label="München Hauptbahnhof",
        car_minutes=35,
        transit_minutes=50,
        bicycle_minutes=20,
    )

    location = saved.session.profile.location
    assert location is not None
    assert location.origin_label == "München Hauptbahnhof"
    assert {
        constraint.mode: constraint.maximum_minutes_one_way
        for constraint in location.travel_constraints
    } == {
        TravelMode.CAR: 35,
        TravelMode.TRANSIT: 50,
        TravelMode.BICYCLE: 20,
        TravelMode.WALK: 15,
    }
    assert (
        next(
            constraint.level
            for constraint in location.travel_constraints
            if constraint.mode == TravelMode.TRANSIT
        )
        == RequirementLevel.MUST_HAVE
    )
    assert (
        next(
            constraint.level
            for constraint in location.travel_constraints
            if constraint.mode == TravelMode.CAR
        )
        == RequirementLevel.PREFERENCE
    )

    cleared = service.save_mobility_preferences(
        workspace.id,
        origin_label="",
        car_minutes=0,
        transit_minutes=0,
        bicycle_minutes=0,
    )

    assert cleared.session.profile.location is None
    assert not [
        fact
        for fact in cleared.session.profile.confirmed_facts
        if fact.key == "location.origin" or fact.key.startswith("commute.")
    ]
    assert not mobility_widget_preferences(cleared.session.profile).is_active


def test_compass_page_suggests_and_saves_a_public_starting_point(tmp_path: Path) -> None:
    container = _container(tmp_path)
    workspace = container.workspaces.create(new_session())
    client = TestClient(create_app(container, data_directory=tmp_path / "data"))

    page = client.get(f"/profile/{workspace.id}")
    assert page.status_code == 200
    assert "data-mobility-preferences" in page.text
    assert 'name="origin_label"' in page.text
    assert 'name="transit_minutes"' in page.text
    assert "not your home address" in page.text

    suggestion = client.post(
        f"/profile/{workspace.id}/location-suggestions",
        data={"query": "München"},
    )
    assert suggestion.status_code == 200
    assert suggestion.json() == {"suggestions": ["München, DE"]}

    saved = client.post(
        f"/profile/{workspace.id}/mobility-preferences",
        data={
            "origin_label": "München",
            "car_minutes": "0",
            "transit_minutes": "60",
            "bicycle_minutes": "30",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "section-location_mobility" in saved.headers["location"]

    reopened = client.get(f"/profile/{workspace.id}")
    assert reopened.status_code == 200
    assert 'value="München, DE"' in reopened.text
    assert 'name="transit_minutes"' in reopened.text
    assert 'value="60"' in reopened.text
    assert ">60 min<" in reopened.text
