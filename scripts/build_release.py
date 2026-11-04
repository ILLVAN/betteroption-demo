"""Build a BetterOption source overlay with conservative runtime-data exclusions."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile

from packaging.version import InvalidVersion, Version


VERSION = "0.7.2k"
PACKAGE_VERSION = "0.7.2+k"
ARCHIVE_NAME = "betteroption_v0_7_2k.zip"
INCLUDED_ROOTS = (
    Path(".env.example"),
    Path(".gitignore"),
    Path("README.md"),
    Path("pyproject.toml"),
    Path("docs"),
    Path("deploy"),
    Path("Dockerfile"),
    Path("compose.yaml"),
    Path(".dockerignore"),
    Path("examples"),
    Path("scripts"),
    Path("src"),
    Path("tests"),
)
FORBIDDEN_PARTS = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "dist",
    "htmlcov",
    "local-backups",
    "local-data",
    "backups",
    "cloudflared-token",
    "uploads",
}
APPROVED_ENVIRONMENT_EXAMPLES = {
    Path(".env.example"),
    Path("deploy/.env.staging.example"),
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".key",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}
# A source release has no reason to contain user-supplied office documents. Keep
# this deny-by-default even outside the normal runtime upload directories. If a
# future release genuinely needs a PDF or office document, review it and add its
# exact repository-relative path to APPROVED_RELEASE_DOCUMENTS.
SENSITIVE_DOCUMENT_SUFFIXES = {
    ".doc",
    ".docx",
    ".odt",
    ".pages",
    ".pdf",
    ".rtf",
}
APPROVED_RELEASE_DOCUMENTS: frozenset[Path] = frozenset()
CANDIDATE_ARTIFACT_SUFFIXES = SENSITIVE_DOCUMENT_SUFFIXES | {
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".png",
    ".text",
    ".tif",
    ".tiff",
    ".txt",
    ".xml",
}
_CANDIDATE_FILENAME_PATTERN = re.compile(
    r"(?:^|[\W_])(?:candidate[\W_]+)?(?:cv|resume|résumé|lebenslauf)(?:$|[\W_])"
    r"|(?:^|[\W_])curriculum[\W_]*vitae(?:$|[\W_])",
    flags=re.IGNORECASE,
)


def _is_runtime_environment_file(path: Path) -> bool:
    """Keep documented examples while excluding every usable environment file."""

    name = path.name.casefold()
    return name.startswith(".env") or name.endswith(".env")


def _is_sensitive_candidate_artifact(relative: Path) -> bool:
    """Exclude unapproved documents and likely user-supplied CV/resume artifacts."""

    if relative in APPROVED_RELEASE_DOCUMENTS:
        return False
    suffix = relative.suffix.casefold()
    if suffix in SENSITIVE_DOCUMENT_SUFFIXES:
        return True
    return suffix in CANDIDATE_ARTIFACT_SUFFIXES and bool(
        _CANDIDATE_FILENAME_PATTERN.search(relative.stem)
    )


def validate_package_version(project_root: Path) -> str:
    """Reject release metadata that pip/setuptools cannot build."""

    pyproject = project_root / "pyproject.toml"
    try:
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        raw_version = str(metadata["project"]["version"])
        normalized_version = str(Version(raw_version))
    except (FileNotFoundError, KeyError, InvalidVersion, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"invalid Python package version in {pyproject}: {exc}") from exc
    if raw_version != PACKAGE_VERSION:
        raise RuntimeError(
            f"Python package version {raw_version!r} does not match {PACKAGE_VERSION!r}"
        )
    if normalized_version != raw_version:
        raise RuntimeError(
            f"Python package version {raw_version!r} is not canonical PEP 440; "
            f"use {normalized_version!r}"
        )
    return raw_version


def _is_link_like(path: Path) -> bool:
    """Reject POSIX symlinks and Windows directory junctions alike."""

    return path.is_symlink() or path.is_junction()


def release_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for included in INCLUDED_ROOTS:
        path = project_root / included
        if _is_link_like(path):
            raise RuntimeError(f"release input must not be a symlink or junction: {included}")
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            relative = candidate.relative_to(project_root)
            normalized_parts = {part.casefold() for part in relative.parts}
            if _is_link_like(candidate):
                raise RuntimeError(f"release input must not be a symlink or junction: {relative}")
            if not candidate.is_file():
                continue
            if (
                (
                    _is_runtime_environment_file(candidate)
                    and relative not in APPROVED_ENVIRONMENT_EXAMPLES
                )
                or FORBIDDEN_PARTS.intersection(normalized_parts)
                or any(part.endswith(".egg-info") for part in relative.parts)
            ):
                continue
            if candidate.suffix.casefold() in FORBIDDEN_SUFFIXES:
                continue
            if _is_sensitive_candidate_artifact(relative):
                continue
            files.append(relative)
    return sorted(set(files))


def build_archive(project_root: Path, destination: Path) -> Path:
    files = release_files(project_root)
    if not files:
        raise RuntimeError("no release files were found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            archive.write(project_root / relative, relative.as_posix())
    return destination


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    package_version = validate_package_version(project_root)
    destination = project_root / "dist" / ARCHIVE_NAME
    archive = build_archive(project_root, destination)
    print(f"Built BetterOption v{VERSION}: {archive}")
    print(f"Python package version: {package_version}")
    print(
        "Known runtime-data paths, runtime environment files, secret-key file types, "
        "database files, likely CV/resume artifacts, and unapproved PDF/office documents "
        "are excluded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
