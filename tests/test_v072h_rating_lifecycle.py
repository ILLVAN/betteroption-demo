from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.employer_reputation import normalize_employer_name
from betteroption.profile_integrity import CompassAction, inspect_compass_integrity
from betteroption.result_repository import (
    ApplicationState,
    InteractionEventKind,
    MatchResultRow,
    MatchRunRow,
)
from betteroption.results import CURRENT_MATCHING_ALGORITHM, ResultService
from betteroption.web import create_app
from test_results_web import build_container, seed_job, seed_workspace, service
from test_v071i_evidence_web import (
    _container,
    _register,
    _seed_workspace_and_job,
    _store_related_job,
)
from test_v072g_dynamic_reranking import _service


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "betteroption" / "web"


def match_events(container, workspace_id, record_id):
    return [
        event
        for event in container.results.interaction_events(workspace_id, record_id)
        if event.kind == InteractionEventKind.MATCH
    ]


def opportunity_cards(html: str) -> list[tuple[str, int | None, str | None]]:
    cards = []
    for tag in re.findall(r'<article class="opportunity-card[^>]*>', html):
        record_match = re.search(r'data-opportunity-record-id="([^"]+)"', tag)
        score_match = re.search(r'data-card-score="([^"]*)"', tag)
        disposition_match = re.search(r'data-card-disposition="([^"]*)"', tag)
        assert record_match is not None
        assert score_match is not None
        assert disposition_match is not None
        cards.append(
            (
                record_match.group(1),
                int(score_match.group(1)) if score_match.group(1) else None,
                disposition_match.group(1) or None,
            )
        )
    return cards


def test_full_match_transitions_discovered_jobs_once(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    first_id, _ = seed_job(container, "lifecycle-first")
    second_id, _ = seed_job(container, "lifecycle-second")
    result_service = service(container)

    result_service.run(workspace)

    for record_id in (first_id, second_id):
        interaction = container.results.get_interaction(workspace.id, record_id)
        assert interaction is not None
        assert interaction.application_state == ApplicationState.MATCHED
        events = match_events(container, workspace.id, record_id)
        assert [(event.kind, event.value) for event in events] == [
            (InteractionEventKind.MATCH, ApplicationState.MATCHED.value)
        ]

    result_service.run(workspace)

    for record_id in (first_id, second_id):
        assert len(match_events(container, workspace.id, record_id)) == 1


def test_single_job_match_only_transitions_the_evaluated_job_and_preserves_later_state(
    tmp_path: Path,
) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    first_id, _ = seed_job(container, "partial-lifecycle-first")
    second_id, _ = seed_job(container, "partial-lifecycle-second")
    result_service = service(container)
    result_service.run(workspace)
    container.results.set_application_state(
        workspace.id,
        first_id,
        ApplicationState.DISCOVERED,
    )
    container.results.set_application_state(
        workspace.id,
        second_id,
        ApplicationState.DISCOVERED,
    )

    result_service.run(workspace, record_ids={first_id})

    first = container.results.get_interaction(workspace.id, first_id)
    second = container.results.get_interaction(workspace.id, second_id)
    assert first is not None and first.application_state == ApplicationState.MATCHED
    assert second is not None and second.application_state == ApplicationState.DISCOVERED
    assert len(match_events(container, workspace.id, first_id)) == 2
    assert len(match_events(container, workspace.id, second_id)) == 1

    container.results.set_application_state(
        workspace.id,
        first_id,
        ApplicationState.SAVED,
    )
    result_service.run(workspace, record_ids={first_id})

    shortlisted = container.results.get_interaction(workspace.id, first_id)
    assert shortlisted is not None
    assert shortlisted.application_state == ApplicationState.SAVED
    assert len(match_events(container, workspace.id, first_id)) == 2


def test_full_match_preserves_every_later_application_state(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    workspace = seed_workspace(container)
    later_states = (
        ApplicationState.SAVED,
        ApplicationState.PREPARING,
        ApplicationState.APPLIED,
        ApplicationState.INTERVIEW,
        ApplicationState.OFFER,
        ApplicationState.REJECTED,
        ApplicationState.WITHDRAWN,
    )
    records_by_state = {
        state: seed_job(container, f"preserve-{state.value}")[0] for state in later_states
    }
    for state, record_id in records_by_state.items():
        container.results.set_application_state(workspace.id, record_id, state)

    service(container).run(workspace)

    for state, record_id in records_by_state.items():
        interaction = container.results.get_interaction(workspace.id, record_id)
        assert interaction is not None
        assert interaction.application_state == state
        assert match_events(container, workspace.id, record_id) == []


def test_rating_surfaces_have_authoritative_hooks_peer_scopes_and_no_store(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, first = _seed_workspace_and_job(container)
        second = _store_related_job(
            container,
            first,
            slug="rating-peer",
            company="Example Products G.m.b.H.",
        )
        _service(container).run(workspace)

        home = client.get("/")
        archive = client.get("/jobs")
        matches = client.get("/matches")
        detail = client.get(f"/jobs/{first.id}")

        for response in (home, archive, matches, detail):
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
        assert 'data-ranked-opportunity-surface="home"' in home.text
        assert 'data-ranked-opportunity-surface="archive"' in archive.text
        assert "data-match-layout" in matches.text
        for response in (home, archive, matches):
            assert f'data-opportunity-record-id="{first.id}"' in response.text
            assert f'data-opportunity-record-id="{second.id}"' in response.text
            assert "data-card-score" in response.text
            assert "data-card-disposition" in response.text
        _, employer_key = normalize_employer_name("Example Products GmbH")
        assert archive.text.count(f'data-rating-scope="employer:{employer_key}"') == 2
        assert archive.text.count('data-application-state-card="matched"') == 2
        assert ">Shortlisted</option>" in archive.text


def test_zero_rating_payload_matches_fresh_layouts_without_boundary_exclusion(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, first = _seed_workspace_and_job(container)
        second = _store_related_job(
            container,
            first,
            slug="home-ranking-peer",
            company="Other Products GmbH",
        )
        _service(container).run(workspace)
        before = client.get("/")
        assert str(first.id) in {
            record_id for record_id, _score, _fit in opportunity_cards(before.text)
        }

        rated = client.post(
            f"/jobs/{first.id}/job-rating",
            data={"stars": "0"},
            headers={"Accept": "application/json"},
        )

        assert rated.status_code == 200
        layout = rated.json()["opportunity_layout"]
        fresh_home = opportunity_cards(client.get("/").text)
        fresh_archive = opportunity_cards(client.get("/jobs").text)
        payload_items = {
            item["record_id"]: (item["score"], item["disposition"]) for item in layout["items"]
        }
        assert layout["home_order"] == [record_id for record_id, _score, _fit in fresh_home]
        assert layout["archive_order"] == [record_id for record_id, _score, _fit in fresh_archive]
        assert payload_items == {
            record_id: (score, disposition) for record_id, score, disposition in fresh_archive
        }
        assert payload_items[str(first.id)] == (0, "stretch")
        assert str(first.id) in layout["home_order"]
        assert str(first.id) in {record_id for record_id, _score, _fit in fresh_home}
        assert str(second.id) in layout["home_order"]


def test_saved_rating_survives_a_projection_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        account, persona, _workspace, record = _seed_workspace_and_job(container)

        def fail_projection(*_args, **_kwargs):
            raise RuntimeError("projection unavailable")

        monkeypatch.setattr(ResultService, "rescore_from_stored_evidence", fail_projection)
        response = client.post(
            f"/jobs/{record.id}/job-rating",
            data={"stars": "4"},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["stars"] == 4
        assert payload["projection_status"] == "failed"
        assert payload["projection_warning"] == payload["ranking_warning"]
        assert "current Match ranking could not be updated" in payload["ranking_warning"]
        rating = container.job_ratings.get(
            persona.id,
            record.id,
            account_id=account.id,
        )
        assert rating is not None
        assert rating.stars == 4


def test_rating_javascript_never_rolls_back_after_server_confirmation() -> None:
    script = (PACKAGE / "static" / "app.js").read_text(encoding="utf-8")
    rating = (PACKAGE / "templates" / "job_rating_control.html").read_text(encoding="utf-8")
    save_rating = script.split("const saveRating = async", 1)[1].split(
        'for (const control of document.querySelectorAll("[data-job-rating-control]"))',
        1,
    )[0]
    after_confirmation = save_rating.split("const savedStars", 1)[1]

    assert "renderRatingControl(peer, kind, previousStars)" in save_rating
    assert "renderRatingControl(peer, kind, previousStars)" not in after_confirmation
    assert "saved.opportunity_layout" in after_confirmation
    assert "new ranking layout could not be shown" in after_confirmation
    assert "activeRatingScopes" in script
    assert 'data-rating-scope="job:' in rating
    assert 'data-rating-scope="employer:' in rating
    assert "event.persisted) window.location.reload()" in script


def test_rating_json_explains_no_match_old_algorithm_and_missing_job(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, first = _seed_workspace_and_job(container)
        seeded_run = container.results.latest_run(workspace.id)
        assert seeded_run is not None
        with container.database.session_factory.begin() as session:
            row = session.get(MatchRunRow, str(seeded_run.id))
            assert row is not None
            session.delete(row)

        no_match = client.post(
            f"/jobs/{first.id}/job-rating",
            data={"stars": "4"},
            headers={"Accept": "application/json"},
        ).json()
        assert no_match["projection_status"] == "no_latest_match"
        assert "No Match ranking exists yet" in no_match["projection_warning"]
        assert no_match["match_layout_updated"] is False

        groups = _service(container).run(workspace)
        with container.database.session_factory.begin() as session:
            row = session.get(MatchRunRow, str(groups.run.id))
            assert row is not None
            row.algorithm_version = "matching-old"
        old_algorithm = client.post(
            f"/jobs/{first.id}/job-rating",
            data={"stars": "3"},
            headers={"Accept": "application/json"},
        ).json()
        assert old_algorithm["projection_status"] == "old_algorithm"
        assert "older scoring algorithm" in old_algorithm["projection_warning"]
        assert old_algorithm["match_layout_updated"] is False

        with container.database.session_factory.begin() as session:
            row = session.get(MatchRunRow, str(groups.run.id))
            assert row is not None
            row.algorithm_version = CURRENT_MATCHING_ALGORITHM
            result_row = session.get(MatchResultRow, str(groups.run.results[0].id))
            assert result_row is not None
            session.delete(result_row)
        missing = client.post(
            f"/jobs/{first.id}/job-rating",
            data={"stars": "2"},
            headers={"Accept": "application/json"},
        ).json()
        assert missing["projection_status"] == "job_missing"
        assert "not part of the latest Match" in missing["projection_warning"]
        assert missing["match_layout_updated"] is False


def test_job_and_employer_ratings_do_not_change_compass_integrity_report_or_gates(
    tmp_path: Path,
) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        account, persona, workspace, record = _seed_workspace_and_job(container)
        before = inspect_compass_integrity(workspace.session)
        gates_before = {action: before.allows(action) for action in CompassAction}

        container.job_ratings.set_rating(
            persona.id,
            record.id,
            0,
            account_id=account.id,
        )
        container.employer_reputation.set_rating(
            persona.id,
            "Example Products GmbH",
            0,
            account_id=account.id,
        )

        reloaded = container.workspaces.get(
            workspace.id,
            account_id=account.id,
            persona_id=persona.id,
        )
        assert reloaded is not None
        after = inspect_compass_integrity(reloaded.session)
        assert after == before
        assert {action: after.allows(action) for action in CompassAction} == gates_before
