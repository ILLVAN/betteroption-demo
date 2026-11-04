"""Privacy-aware local CV text extraction and metadata persistence."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from docx import Document
from pydantic import Field
from pypdf import PdfReader
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import select

from .database import Base, Database
from .profile import StrictModel
from .profile_repository import ProfileWorkspaceRow


MAX_CV_BYTES = 5 * 1024 * 1024
MAX_CV_TEXT = 100_000

_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL_PATTERN = re.compile(
    r"\b(?:https?://|www\.|linkedin\.com/|xing\.com/)\S+",
    re.IGNORECASE,
)
_LABELED_BARE_URL_PATTERN = re.compile(
    r"\b(?:(?:artist|personal)\s+)?(?:web(?:site)?|portfolio|homepage|"
    r"linkedin|xing|github)\s*:\s*(?:[a-z0-9-]+\.)+[a-z]{2,24}"
    r"(?:/[^\s|,;]*)?",
    re.IGNORECASE,
)
_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{6,}\d)(?!\w)")
_DATE_OF_BIRTH_PATTERN = re.compile(
    r"(?im)^(?:date of birth|born|dob|geburtsdatum|geboren)\s*[:\-].*$"
)
_IDENTIFIER_PATTERN = re.compile(
    r"(?im)^(?:nationality|citizenship|passport|identity|id no\.?|"
    r"staatsangehörigkeit|nationalität|ausweis|passnummer|steuer-id)\s*[:\-].*$"
)
_ADDRESS_LINE_PATTERN = re.compile(
    r"(?im)^.*(?:\b\d{5}\s+[\wÄÖÜäöüß.-]+|"
    r"\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?|"
    r"straße|strasse|str\.?|weg|allee|platz|gasse)\s+\d+[a-z]?\b|"
    r"\b\d+[a-z]?\s+(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|"
    r"drive|dr\.?))[^\n]*$"
)
_ROLE_WORDS = {
    "engineer",
    "developer",
    "manager",
    "consultant",
    "designer",
    "analyst",
    "scientist",
    "specialist",
    "technician",
    "architect",
    "student",
    "curriculum",
    "resume",
    "lebenslauf",
    "profil",
}

_SPECIAL_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "health or disability": re.compile(
        r"\b(?:disabled|disability|chronic illness|medical condition|diagnos(?:is|ed)|"
        r"schwerbehind\w*|behinder\w*|pflegegrad|chronisch\w*\s+krank\w*|"
        r"gesundheitlich\w*\s+einschränk\w*)\b",
        re.IGNORECASE,
    ),
    "racial or ethnic origin": re.compile(
        r"\b(?:racial origin|ethnic origin|ethnicity\s*:|race\s*:|"
        r"ethnische\s+herkunft|volkszugehörigkeit)\b",
        re.IGNORECASE,
    ),
    "religion or belief": re.compile(
        r"\b(?:religious affiliation|religion\s*:|church membership|"
        r"religionszugehörigkeit|konfession\s*:|kirchenmitglied)\b",
        re.IGNORECASE,
    ),
    "political opinion or affiliation": re.compile(
        r"\b(?:political affiliation|political opinion|party membership|"
        r"mitglied\s+(?:der|einer)\s+(?:partei|politischen partei)|"
        r"politische\s+(?:meinung|zugehörigkeit))\b",
        re.IGNORECASE,
    ),
    "trade-union membership": re.compile(
        r"\b(?:trade[- ]union member|union membership|gewerkschaftsmitglied|"
        r"gewerkschaftliche\s+mitgliedschaft)\b",
        re.IGNORECASE,
    ),
    "sex life or sexual orientation": re.compile(
        r"\b(?:sexual orientation|sex life|sexuelle orientierung|sexualleben|"
        r"gay|lesbian|bisexual|transgender)\b",
        re.IGNORECASE,
    ),
    "genetic or biometric identification": re.compile(
        r"\b(?:genetic data|dna profile|biometric (?:identifier|template|data)|"
        r"genetische daten|biometrische (?:daten|identifikation))\b",
        re.IGNORECASE,
    ),
    "criminal-offence or security-clearance information": re.compile(
        r"\b(?:criminal conviction|criminal record|convicted of|background check|"
        r"security clearance|vorstrafe|strafregister|führungszeugnis|"
        r"sicherheitsüberprüfung)\b",
        re.IGNORECASE,
    ),
}


class CvRetention(StrEnum):
    UNTIL_DELETED = "until_deleted"
    DELETE_AFTER_EXTRACTION = "delete_after_extraction"


class CvSanitization(StrictModel):
    text: str = Field(min_length=20, max_length=MAX_CV_TEXT)
    redactions: list[str] = Field(default_factory=list)
    blocked_categories: list[str] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_categories)


class CvDocument(StrictModel):
    id: UUID
    workspace_id: UUID
    filename: str
    media_type: str
    file_size: int = Field(ge=1, le=MAX_CV_BYTES)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    extracted_text: str = Field(max_length=MAX_CV_TEXT)
    retention: CvRetention
    uploaded_at: datetime
    reviewed_at: datetime | None = None

    @property
    def text_characters(self) -> int:
        return len(self.extracted_text)


class CvDocumentRow(Base):
    __tablename__ = "cv_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    retention: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CvRepository:
    def __init__(self, database: Database) -> None:
        self.session_factory = database.session_factory

    @staticmethod
    def _to_document(row: CvDocumentRow) -> CvDocument:
        uploaded_at = row.uploaded_at
        if uploaded_at.tzinfo is None:
            uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
        return CvDocument(
            id=UUID(row.id),
            workspace_id=UUID(row.workspace_id),
            filename=row.filename,
            media_type=row.media_type,
            file_size=row.file_size,
            content_hash=row.content_hash,
            extracted_text=row.extracted_text,
            retention=CvRetention(row.retention),
            uploaded_at=uploaded_at,
            reviewed_at=(
                row.reviewed_at.replace(tzinfo=timezone.utc)
                if row.reviewed_at is not None and row.reviewed_at.tzinfo is None
                else row.reviewed_at
            ),
        )

    def save(
        self,
        workspace_id: UUID,
        filename: str,
        media_type: str,
        content: bytes,
        retention: CvRetention,
    ) -> CvDocument:
        extracted_text, canonical_media_type = extract_cv_text(filename, content)
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as database_session:
            if database_session.get(ProfileWorkspaceRow, str(workspace_id)) is None:
                raise KeyError(f"unknown profile workspace: {workspace_id}")
            row = CvDocumentRow(
                id=str(uuid4()),
                workspace_id=str(workspace_id),
                filename=Path(filename).name[:255],
                media_type=canonical_media_type or media_type[:100],
                file_size=len(content),
                content_hash=hashlib.sha256(content).hexdigest(),
                extracted_text=extracted_text,
                retention=retention.value,
                uploaded_at=now,
            )
            database_session.add(row)
            database_session.flush()
            return self._to_document(row)

    def list_for_workspace(self, workspace_id: UUID) -> list[CvDocument]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(CvDocumentRow)
                .where(CvDocumentRow.workspace_id == str(workspace_id))
                .order_by(CvDocumentRow.uploaded_at.desc())
            ).all()
            return [self._to_document(row) for row in rows]

    def get(self, workspace_id: UUID, document_id: UUID) -> CvDocument | None:
        with self.session_factory() as database_session:
            row = database_session.get(CvDocumentRow, str(document_id))
            if row is None or row.workspace_id != str(workspace_id):
                return None
            return self._to_document(row)

    def delete(self, workspace_id: UUID, document_id: UUID) -> bool:
        with self.session_factory.begin() as database_session:
            row = database_session.get(CvDocumentRow, str(document_id))
            if row is None or row.workspace_id != str(workspace_id):
                return False
            database_session.delete(row)
            return True

    def mark_reviewed(self, workspace_id: UUID, document_id: UUID) -> CvDocument:
        with self.session_factory.begin() as database_session:
            row = database_session.get(CvDocumentRow, str(document_id))
            if row is None or row.workspace_id != str(workspace_id):
                raise KeyError(f"unknown CV document: {document_id}")
            row.reviewed_at = datetime.now(timezone.utc)
            database_session.flush()
            return self._to_document(row)


def extract_cv_text(filename: str, content: bytes) -> tuple[str, str]:
    if not content:
        raise ValueError("The CV file is empty.")
    if len(content) > MAX_CV_BYTES:
        raise ValueError("CV files are limited to 5 MB.")
    suffix = Path(filename).suffix.casefold()
    try:
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("The file extension says PDF, but its content is not a PDF.")
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            media_type = "application/pdf"
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("The file is not a valid DOCX document.")
            document = Document(io.BytesIO(content))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif suffix == ".txt":
            text = content.decode("utf-8-sig")
            media_type = "text/plain"
        else:
            raise ValueError("Use a PDF, DOCX, or UTF-8 TXT file.")
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise ValueError("The CV could not be read safely.") from exc
    clean_text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if len(clean_text) < 20:
        raise ValueError("The CV did not contain enough extractable text.")
    return clean_text[:MAX_CV_TEXT], media_type


def _likely_name_header(line: str) -> bool:
    candidate = line.strip()
    if not candidate or len(candidate) > 80 or any(character.isdigit() for character in candidate):
        return False
    words = [word for word in re.split(r"\s+", candidate) if word]
    if not 2 <= len(words) <= 4:
        return False
    normalized_words = {re.sub(r"[^\wÄÖÜäöüß-]", "", word).casefold() for word in words}
    if normalized_words.intersection(_ROLE_WORDS):
        return False
    return all(word[:1].isupper() or (len(word) > 1 and word.isupper()) for word in words if word)


def _redact_phones(text: str) -> tuple[str, bool]:
    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        if sum(character.isdigit() for character in match.group(0)) < 7:
            return match.group(0)
        changed = True
        return "[removed phone number]"

    return _PHONE_PATTERN.sub(replace, text), changed


def sanitize_cv_text(text: str) -> CvSanitization:
    """Remove common direct identifiers and flag prohibited sensitive categories.

    This deterministic local screening is a minimisation aid, not a guarantee.
    The user must still review and edit the exact text before any provider call.
    """

    clean = text.strip()[:MAX_CV_TEXT]
    if len(clean) < 20:
        raise ValueError("The CV did not contain enough reviewable text.")

    redactions: list[str] = []
    first_line, separator, remainder = clean.partition("\n")
    if _likely_name_header(first_line):
        clean = "[removed likely name]" + (separator + remainder if separator else "")
        redactions.append("likely name/header")

    replacements = (
        (_EMAIL_PATTERN, "[removed email address]", "email address"),
        (_LABELED_BARE_URL_PATTERN, "[removed personal URL]", "personal URL"),
        (_URL_PATTERN, "[removed personal URL]", "personal URL"),
        (_DATE_OF_BIRTH_PATTERN, "[removed date of birth]", "date of birth"),
        (_IDENTIFIER_PATTERN, "[removed personal identifier]", "personal identifier"),
        (_ADDRESS_LINE_PATTERN, "[removed exact address]", "exact address"),
    )
    for pattern, replacement, label in replacements:
        clean, count = pattern.subn(replacement, clean)
        if count:
            redactions.append(label)
    clean, phone_changed = _redact_phones(clean)
    if phone_changed:
        redactions.append("phone number")

    clean = "\n".join(line.rstrip() for line in clean.splitlines()).strip()
    blocked_categories = detect_prohibited_categories(clean)
    if len(clean) < 20:
        raise ValueError("Too little CV text remains after local identifier removal.")
    return CvSanitization(
        text=clean[:MAX_CV_TEXT],
        redactions=list(dict.fromkeys(redactions)),
        blocked_categories=blocked_categories,
    )


def canonical_cv_preview_text(text: str) -> str:
    """Normalize browser textarea transport without changing meaningful content."""

    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def detect_prohibited_categories(text: str) -> list[str]:
    """Return category labels only; never return or log matched sensitive text."""

    return [
        category for category, pattern in _SPECIAL_CATEGORY_PATTERNS.items() if pattern.search(text)
    ]
