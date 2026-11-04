from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
import re

from betteroption import __version__
from betteroption.results import CURRENT_MATCHING_ALGORITHM
from scripts.build_release import ARCHIVE_NAME, PACKAGE_VERSION, VERSION


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/README.md",
    ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2k.md",
    ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2k.md",
    ROOT / "docs/archive/discontinued-product-planning/domain-name-decision-v0.7.2i.md",
    ROOT / "docs/archive/discontinued-product-planning/hosting-and-public-roadmap-v0.7.2i.md",
    ROOT / "docs/archive/engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md",
    ROOT / "docs/archive/discontinued-product-planning/roadmap-to-public-release.md",
)


def test_v072k_separates_product_and_pep440_package_identity() -> None:
    assert __version__ == VERSION == "0.7.2k"
    assert PACKAGE_VERSION == "0.7.2+k"
    assert version("betteroption") == PACKAGE_VERSION
    assert ARCHIVE_NAME == "betteroption_v0_7_2k.zip"
    assert CURRENT_MATCHING_ALGORITHM == "matching-v0.7.2i"


def test_v072k_current_documents_exist_and_local_links_resolve() -> None:
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


def test_v072k_handoff_uses_the_installable_release_identity() -> None:
    guide = (ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2k.md").read_text(
        encoding="utf-8"
    )

    assert "betteroption_v0_7_2k.zip" in guide
    assert '-ExpectedVersion "0.7.2k"' in guide
    assert "-ExpectedSha256 $expectedSha256" in guide
    assert "0.7.2+k" in guide
    assert "matching-v0.7.2i" in guide
    assert "0033_background_task_leases" in guide
    assert "No migration, forced rematch, `.env` edit" in guide
    assert "test_release_builder_rejects_symlinked_input" in guide
    assert "test_one_sigint_exits_without_joining_stuck_provider_io" in guide
    release_notes = " ".join(
        (ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2j.md")
        .read_text(encoding="utf-8")
        .split()
    )
    assert "Quickscore never calls a discovery" in release_notes
    assert "2026-08-05-feedback-draft" in release_notes
    assert "test_release.ps1" in guide
    assert "run_web.ps1" in guide
    assert "dump_release.ps1" in guide
    assert 'git tag -a v0.7.2k -m "BetterOption v0.7.2k"' in guide
    assert "git push origin v0.7.2k" in guide

    naming = (
        ROOT / "docs/archive/discontinued-product-planning/domain-name-decision-v0.7.2i.md"
    ).read_text(encoding="utf-8")
    assert "No UI, legal-name, package, repository, email, deployment" in naming


def test_compass_action_hierarchy_and_waiting_copy_match_the_i_contract() -> None:
    compass = (ROOT / "src/betteroption/web/templates/profile_compass.html").read_text(
        encoding="utf-8"
    )
    waiting = (ROOT / "src/betteroption/web/static/task_progress.js").read_text(encoding="utf-8")

    guided = compass.index("Guided setup")
    add = compass.index("Add a job")
    explore = compass.index("Explore jobs")
    matching = compass.index("Open Matching")
    assert guided < add < explore < matching
    assert 'class="primary-button"' in compass[:add]
    assert compass.count('class="secondary-button"') >= 3
    for rejected in (
        "Nothing else needs clicking right now.",
        "Your task survived the page load just fine.",
        "The result will open automatically when ready.",
        "We will bring you back when the useful part is ready.",
        "The next useful click belongs to a later minute.",
    ):
        assert rejected not in waiting


def test_job_feedback_save_actions_use_the_black_primary_style() -> None:
    for name in ("job_detail.html", "match_detail.html"):
        template = (ROOT / "src/betteroption/web/templates" / name).read_text(encoding="utf-8")
        feedback = template.split("How does this opportunity feel", 1)[1]
        save = feedback.split(">Save feedback<", 1)[0].rsplit("<button", 1)[1]
        assert 'class="primary-button"' in save
        assert 'class="confirm-button"' not in save
