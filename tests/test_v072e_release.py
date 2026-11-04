from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_DOCUMENTS = (
    ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2e.md",
    ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2e.md",
)


def test_v072e_historical_documents_exist_and_local_links_resolve() -> None:
    for document in HISTORICAL_DOCUMENTS:
        assert document.is_file(), document
        text = document.read_text(encoding="utf-8")
        for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            target = raw_target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (document.parent / target).resolve()
            assert resolved == ROOT or ROOT in resolved.parents, (document, raw_target)
            assert resolved.exists(), (document, raw_target)


def test_v072e_handoff_preserves_the_unambiguous_packaging_hotfix_record() -> None:
    guide = (ROOT / "docs/archive/engineering-history/local-guides/local-v0.7.2e.md").read_text(
        encoding="utf-8"
    )
    notes = (
        ROOT / "docs/archive/engineering-history/release-notes/release-notes-v0.7.2e.md"
    ).read_text(encoding="utf-8")

    assert "betteroption_v0_7_2e.zip" in guide
    assert '-ExpectedVersion "0.7.2e"' in guide
    assert "0.7.2+e" in guide
    assert "test_release.ps1" in guide
    assert "run_web.ps1" in guide
    assert "dump_release.ps1" in guide
    assert 'git tag -a v0.7.2e -m "BetterOption v0.7.2e"' in guide
    assert "git push origin v0.7.2e" in guide
    assert "v0.7.2d" in guide
    assert "matching-v0.7.2c" in notes
