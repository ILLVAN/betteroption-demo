from __future__ import annotations

from pathlib import Path
import re

from betteroption.results import CURRENT_MATCHING_ALGORITHM


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/README.md",
    ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2d.md",
    ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2d.md",
    ROOT / "docs/archive/engineering-history/providers/job-source-review-v0.7.2d.md",
    ROOT / "docs/archive/engineering-history/providers/discovery-provider-setup-v0.7.2d.md",
    ROOT / "docs/archive/engineering-history/local-guides/local-environment-v0.7.2d.md",
    ROOT / "docs/archive/discontinued-product-planning/domain-name-decision-v0.7.2d.md",
    ROOT / "docs/archive/discontinued-product-planning/roadmap-to-public-release.md",
)


def test_v072d_historical_identity_and_current_matching_version_are_explicit() -> None:
    release_notes = (
        ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2d.md"
    ).read_text(encoding="utf-8")

    assert "Matching algorithm: `matching-v0.7.2c`" in release_notes
    assert CURRENT_MATCHING_ALGORITHM == "matching-v0.7.2i"


def test_v072d_current_documents_exist_and_local_links_resolve() -> None:
    for document in CURRENT_DOCUMENTS:
        assert document.is_file(), document
        text = document.read_text(encoding="utf-8")
        for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = raw_target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (document.parent / target).resolve()
            assert resolved == ROOT or ROOT in resolved.parents, (document, raw_target)
            assert resolved.exists(), (document, raw_target)


def test_v072d_handoff_has_install_test_dump_and_git_commands() -> None:
    guide = (ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2d.md").read_text(
        encoding="utf-8"
    )

    assert "betteroption_v0_7_2d.zip" in guide
    assert '-ExpectedVersion "0.7.2d"' in guide
    assert "diagnose_config.py" in guide
    assert "diagnose_jsearch.py --live" in guide
    assert "test_release.ps1" in guide
    assert "run_web.ps1" in guide
    assert "dump_release.ps1" in guide
    assert "Get-FileHash" in guide
    assert "push_release.ps1" in guide
    assert 'git tag -a v0.7.2d -m "BetterOption v0.7.2d"' in guide
    assert "git push origin v0.7.2d" in guide


def test_v072d_records_jsearch_probe_and_provider_neutral_order() -> None:
    release_notes = (
        ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2d.md"
    ).read_text(encoding="utf-8")
    source_review = (
        ROOT / "docs/archive/engineering-history/providers/job-source-review-v0.7.2d.md"
    ).read_text(encoding="utf-8")
    app = (ROOT / "src/betteroption/web/app.py").read_text(encoding="utf-8")

    assert "returned ten" in release_notes
    assert "provider name is absent from the sort key" in " ".join(source_review.casefold().split())
    assert "Found {row.result_count} usable job(s); {visible} contributed" in app


def test_v072d_keeps_name_stable_and_documents_domain_test_only() -> None:
    base = (ROOT / "src/betteroption/web/templates/base.html").read_text(encoding="utf-8")
    domain_note = (
        ROOT / "docs/archive/discontinued-product-planning/domain-name-decision-v0.7.2d.md"
    ).read_text(encoding="utf-8")

    assert "WorkLifeBalance" in base
    assert "LifeLife.work" not in base
    assert "strongest alternative" in domain_note
    assert "no product or UI rename" in domain_note


def test_v072d_environment_examples_include_current_guards() -> None:
    local = (ROOT / ".env.example").read_text(encoding="utf-8")
    staging = (ROOT / "deploy/.env.staging.example").read_text(encoding="utf-8")

    assert "BETTEROPTION_DISCOVERY_FALLBACK_MIN_RESULTS=60" in local
    assert "BETTEROPTION_EXA_FALLBACK_MIN_RESULTS=" not in local
    for name in (
        "BETTEROPTION_BACKGROUND_WORKER_POLL_SECONDS",
        "BETTEROPTION_BACKGROUND_TASK_MAX_ATTEMPTS",
        "BETTEROPTION_BACKGROUND_TASK_RETRY_SECONDS",
        "BETTEROPTION_OPENWEBNINJA_JSEARCH_ESTIMATED_COST_PER_CALL_USD",
        "BETTEROPTION_COMPANY_RESEARCH_ESTIMATED_COST_PER_CALL_USD",
    ):
        assert f"{name}=" in staging
