from __future__ import annotations

from pathlib import Path

from scripts.build_release import release_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_powershell_dump_uses_the_reviewed_builder_and_an_exact_destination() -> None:
    script_path = PROJECT_ROOT / "scripts" / "dump_release.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert "scripts\\build_release.py" in script
    assert "from scripts.build_release import ARCHIVE_NAME" in script
    assert "^betteroption_v[a-zA-Z0-9_.+-]+\\.zip$" in script
    assert 'Join-Path $projectRoot "dist"' in script
    assert "Remove-Item -LiteralPath $archivePath" in script
    assert "Get-ChildItem" not in script
    assert "Compress-Archive" not in script
    assert ".env" not in script


def test_powershell_dump_is_included_in_the_source_release() -> None:
    assert Path("scripts/dump_release.ps1") in release_files(PROJECT_ROOT)
