from __future__ import annotations

from pathlib import Path
import re

from betteroption.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/README.md",
    ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2c.md",
    ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2c.md",
    ROOT / "docs/archive/engineering-history/providers/job-source-review-v0.7.2c.md",
    ROOT / "docs/archive/engineering-history/providers/discovery-provider-setup-v0.7.2c.md",
    ROOT / "docs/archive/discontinued-product-planning/cost-and-business-plan.md",
    ROOT / "docs/archive/discontinued-product-planning/roadmap-to-public-release.md",
)


def test_current_release_documents_exist_and_local_links_resolve() -> None:
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


def test_release_handoff_contains_every_requested_command_group() -> None:
    guide = (ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2c.md").read_text(
        encoding="utf-8"
    )

    assert "betteroption_v0_7_2c.zip" in guide
    assert '-ExpectedVersion "0.7.2c"' in guide
    assert "diagnose_jsearch.py --live" in guide
    assert "test_release.ps1" in guide
    assert "run_web.ps1" in guide
    assert "dump_release.ps1" in guide
    assert "Get-FileHash" in guide
    assert "push_release.ps1" in guide
    assert 'git tag -a v0.7.2c -m "BetterOption v0.7.2c"' in guide
    assert "git push origin v0.7.2c" in guide


def test_current_operations_and_recipient_notices_match_v072c_behavior() -> None:
    operations = (ROOT / "src/betteroption/web/templates/operations.html").read_text(
        encoding="utf-8"
    )
    privacy = (ROOT / "src/betteroption/web/templates/legal_privacy.html").read_text(
        encoding="utf-8"
    )

    assert "aggregate every operation since 00:00 UTC" in operations
    assert "exact current Explore workflow" in operations
    assert "up to four short independent one-keyword searches" in privacy
    assert "never starts an automatic paid retry" in privacy


def test_fantastic_jobs_is_deferred_and_has_no_runtime_setting() -> None:
    cost_plan = (
        ROOT / "docs/archive/discontinued-product-planning/cost-and-business-plan.md"
    ).read_text(encoding="utf-8")

    assert "Fantastic.jobs is not added" in cost_plan
    assert "manual, bounded benchmark" in cost_plan
    assert not any("fantastic" in name.casefold() for name in Settings.model_fields)


def test_docker_context_excludes_private_artifact_classes() -> None:
    patterns = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

    assert {"backups", "backup", "*.key", "*.pem", "*.p12", "*.pfx"} <= patterns
    assert {"*.doc", "*.docx", "*.odt", "*.pages", "*.pdf", "*.rtf"} <= patterns
