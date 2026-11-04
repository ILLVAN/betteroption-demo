from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from betteroption import __version__
from betteroption.results import CURRENT_MATCHING_ALGORITHM
from scripts.build_release import ARCHIVE_NAME, PACKAGE_VERSION, VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_k_changes_release_identity_without_forcing_a_match_migration() -> None:
    assert __version__ == VERSION == "0.7.2k"
    assert PACKAGE_VERSION == "0.7.2+k"
    assert ARCHIVE_NAME == "betteroption_v0_7_2k.zip"
    assert CURRENT_MATCHING_ALGORITHM == "matching-v0.7.2i"

    notes = (
        ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2k.md"
    ).read_text(encoding="utf-8")
    local = (ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2k.md").read_text(
        encoding="utf-8"
    )
    for text in (notes, local):
        assert "matching-v0.7.2i" in text
        assert "match-evidence-v0.7.2i" in text
        assert "0033_background_task_leases" in text

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.index("Get-FileHash") < readme.index("install_latest_release.ps1")
    assert "ExpectedSha256" in readme


def test_k_first_deploy_runbook_is_stop_gated_and_orders_access_before_route() -> None:
    runbook = (
        ROOT
        / "docs/archive/engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md"
    ).read_text(encoding="utf-8")

    assert "Ubuntu Server 24.04 LTS" in runbook
    assert "download.docker.com/linux/ubuntu" in runbook
    assert "read-only deploy key" in runbook
    assert "sudo -v" in runbook
    assert "PasswordAuthentication no" in runbook
    assert "BETTEROPTION_REGISTRATION_MODE=first_user" in runbook
    assert "BETTEROPTION_REGISTRATION_MODE=invite_only" in runbook
    assert "0033_background_task_leases" in runbook
    assert "matching-v0.7.2i" in runbook
    assert "0.7.2+k" in runbook
    assert "STOP gate" in runbook
    assert "Caddy HTTP access logging is deliberately disabled" in runbook
    assert "default runtime logger removes the complete" in runbook
    assert ".logging.logs.default.encoder.fields.request.filter" in runbook
    assert "max-size: 10m" in runbook
    assert "max-file: 5" in runbook
    assert "size-based" in runbook
    assert "Match this job only" in runbook

    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    worker = compose.split("  worker:", 1)[1].split("  retention:", 1)[0]
    assert "stop_grace_period: 20s" in worker
    assert "driver: json-file" in compose
    assert 'max-size: "10m"' in compose
    assert 'max-file: "5"' in compose
    assert compose.count("logging: *default-logging") == 9

    access = runbook.index("Create the Cloudflare Access wall")
    tunnel = runbook.index("Create the remotely managed Tunnel")
    route = runbook.index("Add the one protected public-hostname route")
    owner = runbook.index("Create exactly one owner")
    assert access < tunnel < route < owner

    caddy = (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")
    assert "no HTTP access log" in caddy
    assert "access.log" not in caddy
    assert re.search(r"log default\s*\{\s*format filter\s*\{\s*request delete", caddy)


def test_j_caddy_adapted_json_removes_the_runtime_request_object() -> None:
    caddy_binary = os.environ.get("CADDY_TEST_BINARY") or shutil.which("caddy")
    if not caddy_binary:
        pytest.skip("set CADDY_TEST_BINARY to exercise Caddy's real adapter")

    environment = dict(os.environ)
    environment["SITE_ADDRESS"] = "alpha.example.test"
    result = subprocess.run(
        [
            caddy_binary,
            "adapt",
            "--config",
            str(ROOT / "deploy/Caddyfile"),
            "--adapter",
            "caddyfile",
            "--validate",
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    adapted = json.loads(result.stdout)
    encoder = adapted["logging"]["logs"]["default"]["encoder"]
    assert encoder["format"] == "filter"
    assert encoder["fields"]["request"]["filter"] == "delete"
    assert all("logs" not in server for server in adapted["apps"]["http"]["servers"].values())


def test_j_abandonable_io_does_not_use_the_interpreter_joining_executor() -> None:
    concurrency = (ROOT / "src/betteroption/concurrency.py").read_text(encoding="utf-8")
    assert "daemon=True" in concurrency
    for path in (ROOT / "src/betteroption").rglob("*.py"):
        if path.name == "concurrency.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"from\s+concurrent\.futures\s+import[^\n]*\bThreadPoolExecutor\b"
            r"|concurrent\.futures\.ThreadPoolExecutor",
            text,
        ), path


def test_j_ui_contract_has_slow_0_to_94_progress_and_no_cancelling_button() -> None:
    javascript = (ROOT / "src/betteroption/web/static/app.js").read_text(encoding="utf-8")
    progress = (ROOT / "src/betteroption/web/templates/task_progress.html").read_text(
        encoding="utf-8"
    )
    detail = (ROOT / "src/betteroption/web/templates/job_detail.html").read_text(encoding="utf-8")
    css = (ROOT / "src/betteroption/web/static/app.css").read_text(encoding="utf-8")

    assert "EXPLORE_PROGRESS_CEILING = 94" in javascript
    assert "EXPLORE_PROGRESS_HORIZON_MS = 9 * 60 * 1000" in javascript
    assert "Cancelling…" not in javascript
    assert "Cancelling…" not in progress
    assert "data-task-stopping" in progress
    assert "Match this job only" in detail
    assert ".evidence-comparison.has-user-override > .evidence-auto" in css
    assert "text-decoration: line-through" in css


def test_j_privacy_copy_matches_disabled_http_access_logging() -> None:
    privacy = (ROOT / "src/betteroption/web/templates/legal_privacy.html").read_text(
        encoding="utf-8"
    )
    storage = (ROOT / "src/betteroption/web/templates/legal_storage.html").read_text(
        encoding="utf-8"
    )
    retention = (
        ROOT
        / "docs/archive/discontinued-product-planning/compliance/07-retention-deletion-schedule.md"
    ).read_text(encoding="utf-8")
    ropa = (
        ROOT
        / "docs/archive/discontinued-product-planning/compliance/02-record-of-processing-activities.md"
    ).read_text(encoding="utf-8")
    lia = (
        ROOT
        / "docs/archive/discontinued-product-planning/compliance/05-legitimate-interests-assessment.md"
    ).read_text(encoding="utf-8")
    toms = (
        ROOT
        / "docs/archive/discontinued-product-planning/compliance/06-technical-organisational-measures.md"
    ).read_text(encoding="utf-8")

    for text in (privacy, storage, retention, ropa, lia, toms):
        assert "Caddy" in text
        assert "runtime/error" in text
        assert "request object" in text or "request` field" in text
        assert "size-based" in text
    assert "does not retain Caddy or Uvicorn HTTP access logs" in privacy
    assert "disables both Caddy and Uvicorn HTTP access logs" in storage
    assert "Caddy and Uvicorn HTTP access logging remain disabled" in retention
    assert "not a fixed time-based retention promise" in storage
    assert "No fixed time period; size-based rotation only" in retention
