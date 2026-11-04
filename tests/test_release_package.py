from __future__ import annotations

from pathlib import Path
import tomllib
from zipfile import ZipFile

from packaging.version import Version
import pytest

from betteroption import __version__
from scripts.build_release import (
    ARCHIVE_NAME,
    PACKAGE_VERSION,
    VERSION,
    build_archive,
    release_files,
    validate_package_version,
)


def test_release_identity_matches_v072() -> None:
    assert __version__ == "0.7.2k"
    assert VERSION == "0.7.2k"
    assert PACKAGE_VERSION == "0.7.2+k"
    assert ARCHIVE_NAME == "betteroption_v0_7_2k.zip"

    project_root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = metadata["project"]["version"]
    assert package_version == PACKAGE_VERSION
    assert str(Version(package_version)) == PACKAGE_VERSION
    assert validate_package_version(project_root) == PACKAGE_VERSION
    assert Path("src/betteroption/data/geonames-DE-postal.zip") in release_files(project_root)
    assert Path("src/betteroption/data/nuts-2024.csv") in release_files(project_root)
    assert Path("src/betteroption/data/nuts-2024.PROVENANCE.md") in release_files(project_root)
    assert Path("src/betteroption/data/nuts-representative-points-2024.csv") in release_files(
        project_root
    )
    assert Path(
        "src/betteroption/data/nuts-representative-points-2024.PROVENANCE.md"
    ) in release_files(project_root)
    assert "data/*.csv" in metadata["tool"]["setuptools"]["package-data"]["betteroption"]
    assert "data/*.md" in metadata["tool"]["setuptools"]["package-data"]["betteroption"]
    installer = (project_root / "scripts" / "install_latest_release.ps1").read_text(
        encoding="utf-8"
    )
    assert "docs\\release-notes-v0.7.0f.md" in installer
    assert "tests\\test_v070a1.py" in installer
    assert "tests\\test_v071a.py" in installer
    assert "ExpectedVersion" in installer
    assert "ExpectedSha256" in installer
    assert installer.index("Get-FileHash") < installer.index("OpenRead")
    assert "cloudflared-token" in installer
    assert "deploy/.env.staging.example" in installer
    assert "runtime environment file" in installer
    test_runner = (project_root / "scripts" / "test_release.ps1").read_text(encoding="utf-8")
    assert "tests\\test_v070a1.py" in test_runner
    assert "tests\\test_v071a.py" in test_runner
    assert Path("Dockerfile") in release_files(project_root)
    assert Path("compose.yaml") in release_files(project_root)
    assert Path("deploy/Caddyfile") in release_files(project_root)
    assert Path("deploy/.env.staging.example") in release_files(project_root)
    assert Path("deploy/scripts/backup_loop.sh") in release_files(project_root)
    assert Path("src/betteroption/retention.py") in release_files(project_root)
    assert Path("src/betteroption/worker.py") in release_files(project_root)
    assert Path("src/betteroption/providers/openai_salary.py") in release_files(project_root)
    assert Path("src/betteroption/providers/apify_all_jobs.py") in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/deployment/netcup-cloudflare-staging-v0.7.1b.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/deployment/deployment-architecture-v0.7.1b.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1b.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1b-legal.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/deployment/netcup-cloudflare-staging-v0.7.1b-legal.md"
    ) in release_files(project_root)
    assert Path("docs/archive/discontinued-product-planning/compliance/README.md") in release_files(
        project_root
    )
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1c-local-quality.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-revival-v0.7.1c.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1d-local-personas.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-personas-provider-recovery-v0.7.1d.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-process/github-release-cycle-v0.7.1d.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1e-account-personas-apply.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-account-personas-apply-v0.7.1e.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1h-workflow-refinement.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-workflow-refinement-v0.7.1h.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1i-evidence-workflow.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-evidence-workflow-v0.7.1i.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1m-local-readiness.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-readiness-v0.7.1m.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1n-local-experience.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-experience-v0.7.1n.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1o-local-quality.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-quality-v0.7.1o.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1p-local-stability.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-stability-v0.7.1p.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1r-search-mobility.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-search-mobility-v0.7.1r.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.1s-source-facts.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-source-facts-v0.7.1s.md"
    ) in release_files(project_root)
    assert Path("docs/README.md") in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.2d.md"
    ) in release_files(project_root)
    assert Path("docs/archive/engineering-history/local-guides/local-v0.7.2d.md") in release_files(
        project_root
    )
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.2e.md"
    ) in release_files(project_root)
    assert Path("docs/archive/engineering-history/local-guides/local-v0.7.2e.md") in release_files(
        project_root
    )
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.2i.md"
    ) in release_files(project_root)
    assert Path("docs/archive/engineering-history/local-guides/local-v0.7.2i.md") in release_files(
        project_root
    )
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.2j.md"
    ) in release_files(project_root)
    assert Path("docs/archive/engineering-history/local-guides/local-v0.7.2j.md") in release_files(
        project_root
    )
    assert Path(
        "docs/archive/engineering-history/release-notes/release-notes-v0.7.2k.md"
    ) in release_files(project_root)
    assert Path("docs/archive/engineering-history/local-guides/local-v0.7.2k.md") in release_files(
        project_root
    )
    assert Path(
        "docs/archive/discontinued-product-planning/domain-name-decision-v0.7.2i.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/discontinued-product-planning/hosting-and-public-roadmap-v0.7.2i.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2i.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2j.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/deployment/netcup-cloudflare-private-alpha-v0.7.2k.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/providers/job-source-review-v0.7.2d.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/providers/discovery-provider-setup-v0.7.2d.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/discontinued-product-planning/cost-and-business-plan.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/discontinued-product-planning/roadmap-to-public-release.md"
    ) in release_files(project_root)
    assert Path("scripts/dump_release.ps1") in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-evidence-v0.7.1k.md"
    ) in release_files(project_root)
    assert Path(
        "docs/archive/engineering-history/local-guides/local-user-controls-v0.7.1g.md"
    ) in release_files(project_root)
    assert Path("src/betteroption/employer_reputation.py") in release_files(project_root)
    assert Path("src/betteroption/posting_date.py") in release_files(project_root)
    assert Path("src/betteroption/job_posters.py") in release_files(project_root)
    assert Path(
        "src/betteroption/migrations/versions/0030_verified_job_posters.py"
    ) in release_files(project_root)
    assert Path(
        "src/betteroption/migrations/versions/0031_private_alpha_roles_feedback.py"
    ) in release_files(project_root)
    assert Path(
        "src/betteroption/migrations/versions/0032_explore_import_origin.py"
    ) in release_files(project_root)
    assert Path(
        "src/betteroption/migrations/versions/0033_background_task_leases.py"
    ) in release_files(project_root)
    assert Path("scripts/bootstrap_local.ps1") in release_files(project_root)
    push_script = (project_root / "scripts" / "push_release.ps1").read_text(encoding="utf-8")
    assert "pyproject.toml" in push_script
    assert "Test-ForbiddenReleasePath" in push_script
    assert ".TrimStart([char]'/')" in push_script
    assert '$leaf.StartsWith(".env"' in push_script
    assert '$leaf.EndsWith(".env"' in push_script
    assert 'Equals("cloudflared-token"' in push_script
    assert "local-backups|local-data|uploads" in push_script
    assert "\\.egg-info(/|$)" in push_script
    assert '".doc", ".docx"' in push_script
    assert '".pyc", ".pyo"' in push_script
    assert "candidateArtifactPattern" in push_script
    dockerignore = (project_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "local-backups" in dockerignore

    dump_script = (project_root / "scripts" / "dump_release.ps1").read_text(encoding="utf-8")
    assert 'Write-Host "DUMP"' in dump_script
    assert 'Write-Host "INSTALL"' in dump_script
    assert 'Write-Host "TEST"' in dump_script
    assert 'Write-Host "GIT UPLOAD' in dump_script
    assert "install_latest_release.ps1" in dump_script
    assert "test_release.ps1" in dump_script
    assert "push_release.ps1" in dump_script


def test_release_builder_rejects_non_pep440_package_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "betteroption"\nversion = "0.7.2e"\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid Python package version"):
        validate_package_version(tmp_path)


def test_release_file_selection_excludes_runtime_profiles_and_secrets(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VERSION = 'test'", encoding="utf-8")
    (tmp_path / "src" / "cv.py").write_text("def parse_cv(): ...", encoding="utf-8")
    (tmp_path / "src" / "candidate-cv.pdf").write_bytes(b"private cv")
    (tmp_path / "src" / "my_resume_2026.txt").write_text("private resume", encoding="utf-8")
    (tmp_path / "src" / "app.egg-info").mkdir()
    (tmp_path / "src" / "app.egg-info" / "PKG-INFO").write_text(
        "generated metadata",
        encoding="utf-8",
    )
    (tmp_path / "src" / "Local-Data").mkdir()
    (tmp_path / "src" / "Local-Data" / "profile.json").write_text(
        "private",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=placeholder", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    (tmp_path / ".ENV.production").write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    (tmp_path / "prod.env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / ".env.staging").write_text(
        "POSTGRES_PASSWORD=secret",
        encoding="utf-8",
    )
    (tmp_path / "deploy" / ".env.staging.example").write_text(
        "POSTGRES_PASSWORD=placeholder",
        encoding="utf-8",
    )
    (tmp_path / "deploy" / ".env.secret.example").write_text(
        "POSTGRES_PASSWORD=still-runtime",
        encoding="utf-8",
    )
    (tmp_path / "deploy" / "origin.pem").write_text("private key", encoding="utf-8")
    (tmp_path / "deploy" / "cloudflared-token").write_text(
        "private tunnel connector token",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "resume-private.docx").write_bytes(b"private resume")
    (tmp_path / "docs" / "product-manual.pdf").write_bytes(b"unreviewed document")
    (tmp_path / "docs" / "release-guide.md").write_text(
        "Public release documentation",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "architecture.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'/>",
        encoding="utf-8",
    )
    (tmp_path / "local-data").mkdir()
    (tmp_path / "local-data" / "profile-private.json").write_text("private", encoding="utf-8")
    (tmp_path / "local-data" / "betteroption.db").write_bytes(b"database")

    selected = release_files(tmp_path)

    assert Path("src/app.py") in selected
    assert Path("src/cv.py") in selected
    assert Path("src/candidate-cv.pdf") not in selected
    assert Path("src/my_resume_2026.txt") not in selected
    assert Path("docs/resume-private.docx") not in selected
    assert Path("docs/product-manual.pdf") not in selected
    assert Path("docs/release-guide.md") in selected
    assert Path("docs/architecture.svg") in selected
    assert Path(".env.example") in selected
    assert Path(".env") not in selected
    assert Path(".ENV.production") not in selected
    assert Path("prod.env") not in selected
    assert Path("deploy/.env.staging.example") in selected
    assert Path("deploy/.env.staging") not in selected
    assert Path("deploy/.env.secret.example") not in selected
    assert Path("deploy/origin.pem") not in selected
    assert Path("deploy/cloudflared-token") not in selected
    assert not any(part.endswith(".egg-info") for path in selected for part in path.parts)
    assert not any("local-data" in path.parts for path in selected)
    assert Path("src/Local-Data/profile.json") not in selected
    assert not any(path.suffix == ".db" for path in selected)


def test_built_archive_contains_source_but_no_runtime_profile_store(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Test release", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VERSION = 'test'", encoding="utf-8")
    (tmp_path / "src" / "candidate-cv.pdf").write_bytes(b"private")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "resume-private.docx").write_bytes(b"private")
    (tmp_path / "docs" / "operator-guide.md").write_text(
        "Safe release documentation",
        encoding="utf-8",
    )
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "candidate-cv.pdf").write_bytes(b"private")
    destination = tmp_path / "output" / "release.zip"

    build_archive(tmp_path, destination)

    with ZipFile(destination) as archive:
        names = set(archive.namelist())
    assert "README.md" in names
    assert "src/app.py" in names
    assert "docs/operator-guide.md" in names
    assert "src/candidate-cv.pdf" not in names
    assert "docs/resume-private.docx" not in names
    assert not any(name.startswith("uploads/") for name in names)
    assert not any(name.endswith((".db", ".sqlite", ".sqlite3")) for name in names)


def test_release_builder_rejects_symlinked_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use ordinary placeholders and model the exact lstat result observed by
    # the builder. Creating real symlinks requires Developer Mode or elevated
    # privileges on Windows, so fixture setup must not decide whether this
    # security boundary is tested.
    file_case = tmp_path / "file-case"
    source = file_case / "src"
    file_case.mkdir()
    source.mkdir()
    linked_file = source / "linked.txt"
    linked_file.write_text("must never enter the archive", encoding="utf-8")
    real_is_symlink = Path.is_symlink

    with monkeypatch.context() as link_context:
        link_context.setattr(
            Path,
            "is_symlink",
            lambda candidate: candidate == linked_file or real_is_symlink(candidate),
        )
        with pytest.raises(RuntimeError, match="must not be a symlink or junction"):
            release_files(file_case)

    directory_case = tmp_path / "directory-case"
    linked_directory = directory_case / "docs"
    linked_directory.mkdir(parents=True)
    (linked_directory / "private.txt").write_text("private", encoding="utf-8")

    with monkeypatch.context() as link_context:
        link_context.setattr(
            Path,
            "is_symlink",
            lambda candidate: candidate == linked_directory or real_is_symlink(candidate),
        )
        with pytest.raises(
            RuntimeError,
            match=r"must not be a symlink or junction: docs",
        ):
            release_files(directory_case)

    junction_case = tmp_path / "junction-case"
    junction_directory = junction_case / "docs"
    junction_directory.mkdir(parents=True)
    real_is_junction = Path.is_junction

    with monkeypatch.context() as junction_context:
        junction_context.setattr(
            Path,
            "is_junction",
            lambda candidate: candidate == junction_directory or real_is_junction(candidate),
        )
        with pytest.raises(
            RuntimeError,
            match=r"must not be a symlink or junction: docs",
        ):
            release_files(junction_case)
