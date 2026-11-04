from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from betteroption.job_context import EmployerContextService
from betteroption.jobs import load_job
from betteroption.matching import MatchDisposition, match_job
from betteroption.results import ResultService
from betteroption.web import create_app
from test_jobs import SAMPLE_DIRECTORY, matching_profile
from test_v071i_evidence_web import (
    _container,
    _register,
    _seed_workspace_and_job,
    _store_related_job,
)


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "betteroption" / "web"


def _service(container) -> ResultService:
    return ResultService(
        container.repository,
        container.job_corpus_service(),
        container.results,
        container.access_policy,
        employer_context=EmployerContextService(research_homepages=False),
        job_overrides=container.job_overrides,
        employer_reputation=container.employer_reputation,
        job_ratings=container.job_ratings,
    )


def test_non_blocked_group_always_follows_the_displayed_score() -> None:
    job = load_job(SAMPLE_DIRECTORY / "fpga_research.json")

    automatic = match_job(matching_profile(), job)
    positively_rated = match_job(
        matching_profile(),
        job,
        employer_reputation_stars=5,
        job_rating_stars=5,
    )

    assert automatic.score == 63
    assert automatic.hard_evidence_coverage == 0
    assert automatic.disposition == MatchDisposition.TOP
    assert positively_rated.score == 79
    assert positively_rated.disposition == MatchDisposition.TOP


def test_rating_json_returns_the_complete_persisted_layout(tmp_path: Path) -> None:
    container = _container(tmp_path)
    app = create_app(container, data_directory=tmp_path / "data")

    with TestClient(app) as client:
        _register(client)
        _account, _persona, workspace, first = _seed_workspace_and_job(container)
        second = _store_related_job(
            container,
            first,
            slug="second-role",
            company="Example Products G.m.b.H.",
        )
        _service(container).run(workspace)

        response = client.post(
            f"/jobs/{first.id}/employer-rating",
            data={"stars": "5"},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["match_layout_updated"] is True
        assert payload["projection_status"] == "updated"
        assert payload["projection_warning"] is None
        layout = payload["match_layout"]
        latest = container.results.latest_run(workspace.id)
        assert latest is not None
        assert layout["run_id"] == str(latest.id)
        assert [item["record_id"] for item in layout["items"]] == [
            str(item.job_record_id) for item in latest.results
        ]
        assert [item["position"] for item in layout["items"]] == list(
            range(1, len(latest.results) + 1)
        )
        assert sum(layout["counts"].values()) == len(latest.results)
        assert {item["record_id"] for item in layout["items"]} == {
            str(first.id),
            str(second.id),
        }

        page = client.get("/matches")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert 'data-match-layout data-match-run-id="' in page.text
        for disposition in ("top", "stretch", "blocked"):
            assert f'data-match-grid="{disposition}"' in page.text
            assert f'data-match-empty="{disposition}"' in page.text
            assert f'data-match-summary-count="{disposition}"' in page.text
        for item in layout["items"]:
            assert f'data-match-record-id="{item["record_id"]}"' in page.text
            assert f'data-match-position="{item["position"]}"' in page.text


def test_rating_frontend_applies_server_layout_with_fast_reduced_motion_safe_switches() -> None:
    script = (PACKAGE / "static" / "app.js").read_text(encoding="utf-8")
    css = (PACKAGE / "static" / "app.css").read_text(encoding="utf-8")

    assert "applyAuthoritativeMatchLayout" in script
    assert "saved.score_updates" in script
    assert "saved.match_layout" in script
    assert "saved.opportunity_layout" in script
    assert "grid.append(card)" in script
    layout_move = script.split("for (const item of layout.items)", 1)[1].split(
        "for (const disposition", 1
    )[0]
    disposition_update = "card.dataset.matchDisposition = item.disposition;"
    assert disposition_update in layout_move
    assert layout_move.index(disposition_update) < layout_move.index("grid.append(card)")
    assert "old.disposition !== card.dataset.matchDisposition" in script
    assert "layout.counts?.[disposition]" in script
    assert "event.persisted" in script
    assert ".match-card-is-moving" in css
    assert "match-card-position-switch .18s" in css
    reduced_motion = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]
    assert ".match-card-is-moving" in reduced_motion
