"""Source-grounded application contact details and persona-owned corrections.

Only information published in the job advertisement is extracted.  The module
does not discover people elsewhere on the web and deliberately keeps
advertisement evidence separate from private user corrections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import json
import re
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, Field, model_validator
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .profile import StrictModel


class ApplicationChannel(StrEnum):
    EMPLOYER_PORTAL = "employer_portal"
    EMAIL = "email"
    POSTAL = "postal"
    OTHER = "other"


class GuidanceProvenance(StrEnum):
    ADVERTISEMENT = "advertisement"
    USER_OVERRIDE = "user_override"


class ApplicationGuidanceEntry(StrictModel):
    """One value with provenance; source values always carry verbatim evidence."""

    value: str = Field(min_length=1, max_length=2_000)
    provenance: GuidanceProvenance = GuidanceProvenance.ADVERTISEMENT
    evidence_quote: str | None = Field(default=None, min_length=1, max_length=2_000)
    source_url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def advertisement_values_have_evidence(self) -> ApplicationGuidanceEntry:
        if self.provenance == GuidanceProvenance.ADVERTISEMENT and not self.evidence_quote:
            raise ValueError("advertisement guidance requires a verbatim evidence quote")
        if self.provenance == GuidanceProvenance.USER_OVERRIDE and self.evidence_quote is not None:
            raise ValueError("user corrections must not claim advertisement evidence")
        return self


class ApplicationGuidance(StrictModel):
    """Application metadata explicitly present in one public advertisement."""

    contact_name: ApplicationGuidanceEntry | None = None
    contact_role: ApplicationGuidanceEntry | None = None
    contact_email: ApplicationGuidanceEntry | None = None
    contact_phone: ApplicationGuidanceEntry | None = None
    postal_address: ApplicationGuidanceEntry | None = None
    application_channel: ApplicationGuidanceEntry | None = None
    application_url: ApplicationGuidanceEntry | None = None
    requested_documents: tuple[ApplicationGuidanceEntry, ...] = ()
    max_file_size: ApplicationGuidanceEntry | None = None
    max_pages: ApplicationGuidanceEntry | None = None
    application_deadline: ApplicationGuidanceEntry | None = None
    instructions: tuple[ApplicationGuidanceEntry, ...] = ()

    def entries(self) -> tuple[ApplicationGuidanceEntry, ...]:
        singles = (
            self.contact_name,
            self.contact_role,
            self.contact_email,
            self.contact_phone,
            self.postal_address,
            self.application_channel,
            self.application_url,
            self.max_file_size,
            self.max_pages,
            self.application_deadline,
        )
        return (
            tuple(item for item in singles if item is not None)
            + tuple(self.requested_documents)
            + tuple(self.instructions)
        )

    @property
    def is_empty(self) -> bool:
        return not self.entries()


class ApplicationGuidanceField(StrEnum):
    CONTACT_NAME = "contact_name"
    CONTACT_ROLE = "contact_role"
    CONTACT_EMAIL = "contact_email"
    CONTACT_PHONE = "contact_phone"
    POSTAL_ADDRESS = "postal_address"
    APPLICATION_CHANNEL = "application_channel"
    APPLICATION_URL = "application_url"
    REQUESTED_DOCUMENTS = "requested_documents"
    MAX_FILE_SIZE = "max_file_size"
    MAX_PAGES = "max_pages"
    APPLICATION_DEADLINE = "application_deadline"
    INSTRUCTIONS = "instructions"


class ApplicationGuidanceOverride(StrictModel):
    """A complete typed patch; edited_fields distinguishes clear from inherit."""

    workspace_id: UUID
    job_record_id: UUID
    edited_fields: frozenset[ApplicationGuidanceField] = frozenset()
    contact_name: str | None = Field(default=None, max_length=300)
    contact_role: str | None = Field(default=None, max_length=300)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=100)
    postal_address: str | None = Field(default=None, max_length=500)
    application_channel: ApplicationChannel | None = None
    application_url: str | None = Field(default=None, max_length=2_000)
    requested_documents: tuple[str, ...] = ()
    max_file_size: str | None = Field(default=None, max_length=100)
    max_pages: int | None = Field(default=None, ge=1, le=1_000)
    application_deadline: str | None = Field(default=None, max_length=200)
    instructions: tuple[str, ...] = ()
    updated_at: datetime

    @model_validator(mode="after")
    def edited_values_are_safe(self) -> ApplicationGuidanceOverride:
        if self.contact_email and not re.fullmatch(
            r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
            self.contact_email,
            flags=re.IGNORECASE,
        ):
            raise ValueError("contact_email must be a valid email address")
        if self.application_url:
            parsed = AnyHttpUrl(self.application_url)
            object.__setattr__(self, "application_url", str(parsed))
        return self


class ApplicationGuidanceOverrideRow(Base):
    __tablename__ = "job_application_guidance_overrides"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "job_record_id",
            name="uq_job_application_guidance_workspace_job",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("profile_workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    edited_fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


class ApplicationGuidanceOverrideRepository:
    """Persist guidance corrections for one persona and job.

    Compass workspaces can be replaced while the owning persona remains the
    same.  Existing rows therefore retain their original workspace foreign key,
    but repository operations follow the persona across all of its workspaces.
    Legacy workspaces without a persona remain strictly workspace-scoped.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_model(row: ApplicationGuidanceOverrideRow) -> ApplicationGuidanceOverride:
        payload = json.loads(row.payload_json)
        return ApplicationGuidanceOverride(
            workspace_id=UUID(row.workspace_id),
            job_record_id=UUID(row.job_record_id),
            edited_fields=frozenset(json.loads(row.edited_fields_json)),
            updated_at=_ensure_utc(row.updated_at),
            **payload,
        )

    @staticmethod
    def _scope_workspace_ids(database_session, workspace_id: UUID) -> list[str]:
        # Lazy import keeps the standalone guidance value models usable from
        # jobs.py without introducing an import cycle through repositories.
        from .profile_repository import ProfileWorkspaceRow

        workspace = database_session.get(ProfileWorkspaceRow, str(workspace_id))
        if workspace is None:
            raise KeyError(f"unknown persona workspace: {workspace_id}")
        if workspace.persona_id is None:
            return [workspace.id]
        return list(
            database_session.scalars(
                select(ProfileWorkspaceRow.id).where(
                    ProfileWorkspaceRow.persona_id == workspace.persona_id
                )
            ).all()
        )

    @staticmethod
    def _latest_for_job(database_session, workspace_ids: list[str], job_record_id: UUID):
        """Return the deterministic effective row, including legacy duplicates."""

        return database_session.scalar(
            select(ApplicationGuidanceOverrideRow)
            .where(
                ApplicationGuidanceOverrideRow.workspace_id.in_(workspace_ids),
                ApplicationGuidanceOverrideRow.job_record_id == str(job_record_id),
            )
            .order_by(
                ApplicationGuidanceOverrideRow.updated_at.desc(),
                ApplicationGuidanceOverrideRow.created_at.desc(),
                ApplicationGuidanceOverrideRow.id.desc(),
            )
            .limit(1)
        )

    def get(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
    ) -> ApplicationGuidanceOverride | None:
        with self.session_factory() as database_session:
            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            row = self._latest_for_job(database_session, workspace_ids, job_record_id)
            return self._to_model(row) if row else None

    def save(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        *,
        edited_fields: set[ApplicationGuidanceField] | frozenset[ApplicationGuidanceField],
        contact_name: str | None = None,
        contact_role: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        postal_address: str | None = None,
        application_channel: ApplicationChannel | None = None,
        application_url: str | None = None,
        requested_documents: tuple[str, ...] | list[str] = (),
        max_file_size: str | None = None,
        max_pages: int | None = None,
        application_deadline: str | None = None,
        instructions: tuple[str, ...] | list[str] = (),
    ) -> ApplicationGuidanceOverride:
        clean_fields = frozenset(edited_fields)
        clean_postal_address = _clean_optional(postal_address)
        if clean_postal_address is not None:
            clean_postal_address = _clean_merged_postal_address(clean_postal_address) or None
        payload = {
            "contact_name": _clean_optional(contact_name),
            "contact_role": _clean_optional(contact_role),
            "contact_email": _clean_optional(contact_email),
            "contact_phone": _clean_optional(contact_phone),
            "postal_address": clean_postal_address,
            "application_channel": application_channel,
            "application_url": _clean_optional(application_url),
            "requested_documents": tuple(_clean_many(requested_documents)),
            "max_file_size": _clean_optional(max_file_size),
            "max_pages": max_pages,
            "application_deadline": _clean_optional(application_deadline),
            "instructions": tuple(_clean_many(instructions)),
        }
        validated = ApplicationGuidanceOverride(
            workspace_id=workspace_id,
            job_record_id=job_record_id,
            edited_fields=clean_fields,
            updated_at=_utc_now(),
            **payload,
        )
        serialized = validated.model_dump(
            mode="json", exclude={"workspace_id", "job_record_id", "edited_fields", "updated_at"}
        )
        now = validated.updated_at
        with self.session_factory.begin() as database_session:
            # Lazy imports keep the guidance value models usable from jobs.py
            # without creating a jobs -> guidance -> repository -> jobs cycle.
            from .job_repository import JobRecordRow

            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            if database_session.get(JobRecordRow, str(job_record_id)) is None:
                raise KeyError(f"unknown job: {job_record_id}")
            row = self._latest_for_job(database_session, workspace_ids, job_record_id)
            if row is None:
                row = ApplicationGuidanceOverrideRow(
                    id=str(uuid4()),
                    workspace_id=str(workspace_id),
                    job_record_id=str(job_record_id),
                    payload_json=json.dumps(serialized, ensure_ascii=False),
                    edited_fields_json=json.dumps(sorted(field.value for field in clean_fields)),
                    created_at=now,
                    updated_at=now,
                )
                database_session.add(row)
            else:
                row.payload_json = json.dumps(serialized, ensure_ascii=False)
                row.edited_fields_json = json.dumps(sorted(field.value for field in clean_fields))
                row.updated_at = now
            database_session.flush()
            return self._to_model(row)

    def delete(self, workspace_id: UUID, job_record_id: UUID) -> bool:
        with self.session_factory.begin() as database_session:
            workspace_ids = self._scope_workspace_ids(database_session, workspace_id)
            result = database_session.execute(
                delete(ApplicationGuidanceOverrideRow).where(
                    ApplicationGuidanceOverrideRow.workspace_id.in_(workspace_ids),
                    ApplicationGuidanceOverrideRow.job_record_id == str(job_record_id),
                )
            )
            return bool(result.rowcount)

    def effective(
        self,
        workspace_id: UUID,
        job_record_id: UUID,
        extracted: ApplicationGuidance,
    ) -> ApplicationGuidance:
        override = self.get(workspace_id, job_record_id)
        return apply_application_guidance_override(extracted, override)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    clean = " ".join(value.split())
    return clean or None


def _clean_many(values: tuple[str, ...] | list[str]) -> list[str]:
    return [clean for value in values if (clean := " ".join(value.split()))]


def _user_entry(value: str | int | ApplicationChannel | None) -> ApplicationGuidanceEntry | None:
    if value is None:
        return None
    text = value.value if isinstance(value, ApplicationChannel) else str(value)
    if not text.strip():
        return None
    return ApplicationGuidanceEntry(
        value=text.strip(),
        provenance=GuidanceProvenance.USER_OVERRIDE,
    )


def apply_application_guidance_override(
    extracted: ApplicationGuidance,
    override: ApplicationGuidanceOverride | None,
) -> ApplicationGuidance:
    if override is None:
        return extracted
    update: dict[str, object] = {}
    for field in override.edited_fields:
        value = getattr(override, field.value)
        if field in {
            ApplicationGuidanceField.REQUESTED_DOCUMENTS,
            ApplicationGuidanceField.INSTRUCTIONS,
        }:
            update[field.value] = tuple(_user_entry(item) for item in value)
        elif field == ApplicationGuidanceField.POSTAL_ADDRESS:
            clean_address = _clean_optional(value)
            if clean_address is not None:
                clean_address = _clean_merged_postal_address(clean_address) or None
            update[field.value] = _user_entry(clean_address)
        else:
            update[field.value] = _user_entry(value)
    return extracted.model_copy(update=update)


_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\]\[()]+", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+\s?\d{1,3}|00\s?\d{1,3}|0\d)[\d ()/.-]{6,}\d")
_POSTAL_ADDRESS_LABEL_RE = re.compile(
    r"(?:postanschrift|bewerbungsadresse|postal address|mailing address|application address|"
    r"adresse postale|adresse de candidature|direcci[oó]n postal|direcci[oó]n de solicitud|"
    r"indirizzo postale|indirizzo (?:per la )?candidatura|correspondentieadres|"
    r"sollicitatieadres|adres korespondencyjny|adres aplikacji)"
    r"\s*[:|\-–—]?\s*(?P<body>.*)",
    re.IGNORECASE,
)
_STREET_ADDRESS_RE = re.compile(
    r"(?:"
    r"[\wÀ-ÖØ-öø-ÿ.'’\- ]{2,80}"
    r"(?:straße|strasse|str\.?|weg|allee|platz|gasse|ring|ufer|"
    r"chaussee|damm|markt|hof|promenade|street|road|avenue|lane|drive|"
    r"boulevard|rue|chemin|quai|via|viale|piazza|calle|carrer|avenida|"
    r"paseo|straat|laan|plein|ulica|ul\.)\s+\d+[\w/\-]*"
    r"|"
    r"\d+[\w/\-]*\s+[\wÀ-ÖØ-öø-ÿ.'’\- ]{2,80}"
    r"(?:street|road|avenue|lane|drive|boulevard)"
    r")",
    re.IGNORECASE,
)
_STREET_CORE_RE = re.compile(
    r"(?:"
    r"(?:rue|chemin|quai|via|viale|piazza|calle|carrer|avenida|paseo|ulica|ul\.?)"
    r"\s+[\wÀ-ÖØ-öø-ÿ.'’\-]+(?:\s+[\wÀ-ÖØ-öø-ÿ.'’\-]+){0,5}\s+\d+[\w/\-]*"
    r"|"
    r"[\wÀ-ÖØ-öø-ÿ.'’\-]+(?:\s+[\wÀ-ÖØ-öø-ÿ.'’\-]+){0,5}"
    r"(?:straße|strasse|str\.?|weg|allee|platz|gasse|ring|ufer|chaussee|damm|"
    r"markt|hof|promenade|street|road|avenue|lane|drive|boulevard|rue|chemin|"
    r"quai|via|viale|piazza|calle|carrer|avenida|paseo|straat|laan|plein|ulica|ul\.)"
    r"\s+\d+[\w/\-]*"
    r"|\d+[\w/\-]*\s+[\wÀ-ÖØ-öø-ÿ.'’\-]+"
    r"(?:\s+[\wÀ-ÖØ-öø-ÿ.'’\-]+){0,5}\s+"
    r"(?:street|road|avenue|lane|drive|boulevard)"
    r")",
    re.IGNORECASE,
)
_POSTCODE_CITY_RE = re.compile(
    r"(?:\b(?:[A-Z]{1,2}[\s-]?)?\d{4,6}\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ.'’\- ]{1,70}\b|"
    r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b)",
    re.IGNORECASE,
)
_SCHEMA_POSTAL_ADDRESS_RE = re.compile(
    r"PostalAddress\s+(?P<country>Deutschland|Germany|DE)\s+"
    r"(?P<place>.+?)\s+(?P<postcode>\d{5})\s+"
    r"(?:Nicht\s+vorhanden|Not\s+available)",
    re.IGNORECASE,
)

_APPLICATION_CONTEXT_MARKERS = (
    "ansprech",
    "auswahlprozess",
    "applica",
    "apply",
    "bewerb",
    "candidat",
    "contact",
    "contatto",
    "contactpersoon",
    "curriculum vitae",
    "documents",
    "e-mail",
    "email",
    "kontakt",
    "lebenslauf",
    "interview",
    "entretien",
    "colloquio",
    "gespräch",
    "unterlagen",
    "postul",
    "proceso de selección",
    "processus de recrutement",
    "processo di selezione",
    "selection process",
    "sollicitatieprocedure",
    "recrut",
    "recruit",
    "solicitud",
    "sollicit",
    "stuur",
    "wyślij",
)
_CONTACT_HEADING_RE = re.compile(
    r"(?:"
    r"ansprechperson|ansprechpartner(?:in)?|ihr(?:e)? kontakt(?:person)?|kontaktperson|"
    r"contact person|your contact|hiring contact|recruiting contact|"
    r"votre contact|personne de contact|contact recrutement|"
    r"persona de contacto|contacto de selecci[oó]n|"
    r"referente|persona da contattare|contactpersoon|"
    r"osoba kontaktowa|kontakt rekrutacyjny"
    r")",
    re.IGNORECASE,
)
_CONTACT_LABEL_RE = re.compile(
    rf"{_CONTACT_HEADING_RE.pattern}\s*(?:(?:ist|is|est|es|è)\s+|[:|\-–—]\s*)(?P<body>.+)",
    re.IGNORECASE,
)
_CONTACT_SENTENCE_PATTERNS = (
    re.compile(
        r"(?:wenden sie sich(?: bitte)? an|kontaktieren sie(?: bitte)?|"
        r"melde dich(?: gerne)? bei|"
        r"please contact|contactez|contacte con|contacta con|contatta|"
        r"neem contact op met|skontaktuj si[eę] z|reach out to)\s+"
        r"(?P<body>[^.;\n]{3,180})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:für|bei)\s+(?:fachliche[n]?\s+)?(?:rück)?fragen[^.\n]{0,80}?"
        r"steht\s+(?:dir|euch|ihnen)\s+(?P<body>[^.;\n]{3,160}?)\s+"
        r"(?:gerne\s+)?zur\s+verfügung",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:für|bei)\s+(?:fachliche[n]?\s+)?(?:rück)?fragen[^.\n]{0,80}?"
        r"(?:kannst du dich|können sie sich)\s+(?:gerne\s+)?an\s+"
        r"(?P<body>[^.;\n]{3,160}?)\s+wenden",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:fragen beantwortet|bei fragen hilft)\s+(?:dir|euch|ihnen)\s+"
        r"(?P<body>[^.;\n]{3,160}?)(?:\s+gerne)?\s+(?:weiter|$)",
        re.IGNORECASE,
    ),
)
_ROLE_MARKERS = (
    "acquisition",
    "business partner",
    "director",
    "engineering",
    "geschäfts",
    "head of",
    "human resources",
    "hr ",
    "lead",
    "leiter",
    "leitung",
    "manager",
    "people & culture",
    "personal",
    "recrut",
    "recruit",
    "responsable",
    "recursos humanos",
    "ressources humaines",
    "risorse umane",
    "talent",
)

_PORTAL_CHANNEL_MARKERS = (
    "apply button",
    "apply online",
    "apply through our",
    "application portal",
    "bewerbungsportal",
    "career portal",
    "career site",
    "carrières",
    "karriereportal",
    "bewerben-button",
    "jetzt bewerben",
    "online bewerben",
    "online-bewerbung",
    "portal de empleo",
    "portal de emprego",
    "portal rekrutacyjny",
    "portale carriera",
    "postulez en ligne",
    "solliciteren via",
    "über unser online",
    "via ons online",
)
_EMAIL_CHANNEL_MARKERS = (
    "application by email",
    "application via email",
    "bewerbung per e-mail",
    "bewerbung per email",
    "bewerbung an",
    "bewerbung bitte an",
    "candidature par e-mail",
    "candidatura por correo",
    "candidatura via e-mail",
    "email your application",
    "envoyez votre candidature",
    "par e-mail",
    "por correo electrónico",
    "por email",
    "per e-mail",
    "per email",
    "per e-mail bewerben",
    "per email bewerben",
    "send your application",
    "senden sie ihre bewerbung",
    "stuur je sollicitatie",
    "via email",
    "via e-mail",
)
_POSTAL_CHANNEL_MARKERS = (
    "bewerbung per post",
    "by post",
    "candidature par courrier",
    "postalisch",
    "send by post",
)
_POSTAL_DELIVERY_MARKERS = (
    *_POSTAL_CHANNEL_MARKERS,
    "bewerbungsadresse",
    "application address",
    "adresse de candidature",
    "adres aplikacji",
    "candidature à l'adresse",
    "candidatura all'indirizzo",
    "candidatura por correo postal",
    "dirección de solicitud",
    "envoyez votre candidature à",
    "indirizzo per la candidatura",
    "indirizzo per candidature",
    "postanschrift",
    "postal address",
    "send your application to",
    "senden sie ihre bewerbung an",
    "sollicitatieadres",
)
_INSTRUCTION_MARKERS = (
    "apply online",
    "apply through",
    "apply via",
    "bewerben sie sich",
    "bewerbung an",
    "bitte bewerben",
    "bitte bewirb",
    "bitte reichen",
    "bitte senden",
    "schick uns",
    "schicken sie",
    "candidatura",
    "envoyez votre candidature",
    "invia la tua candidatura",
    "please send",
    "please submit",
    "postulez",
    "reichen sie",
    "send your application",
    "senden sie",
    "solliciteren",
    "stuur je sollicitatie",
    "wyślij",
)
_PROCESS_MARKERS = (
    "application process",
    "assessment center",
    "auswahlprozess",
    "bewerbungsprozess",
    "entretien",
    "interview",
    "colloquio",
    "proceso de selección",
    "processo di selezione",
    "recruitment process",
    "selection process",
    "sollicitatieprocedure",
    "telefoninterview",
    "vorstellungsgespräch",
)

# Fail-closed sentence patterns for provider minimisation.  Deterministic field
# extraction intentionally stays conservative so it does not invent a person's
# identity; provider-bound text needs the opposite failure mode.  If a source
# uses an uncommon but clearly contact-shaped phrase, BetterOption withholds the
# complete sentence rather than guessing which tokens form a name.
_PROVIDER_PRIVATE_CONTACT_PATTERNS = (
    re.compile(
        r"(?:bewerbungskontakt|ansprechpartner(?:in)?|kontaktperson|personalkontakt|"
        r"contact person|application contact|recruiting contact|hiring manager|"
        r"persona de contacto|contacto de selecci[oó]n|personne de contact|"
        r"contact recrutement|referente per la candidatura|contactpersoon|"
        r"osoba kontaktowa)\s*[:|\-–—]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:questions?|fragen|r[uü]ckfragen|preguntas|questions concernant|domande)"
        r".{0,140}(?:talk to|contact|directed to|reach out|answered by|wenden|"
        r"kontaktier|contacter|contactar|rivolgersi|skontakt)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:your|ihr(?:e)?|dein(?:e)?|votre|tu|su|jouw)?\s*"
        r"(?:recruiter|hiring manager|contact person|kontaktperson|ansprechpartner(?:in)?)"
        r"\s*(?:is|will be|ist|wird|es|est|sar[aà]|:)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:send|submit|email|forward|senden|schicken|schick|reichen|envoy|"
        r"env[ií]a|invia|stuur|wy[sś]lij).{0,80}"
        r"(?:application|bewerbung|candidature|candidatura|solicitud|sollicitatie|"
        r"cv|lebenslauf).{0,40}(?:\bto\b|\ban\b|\b[aà]\b|\bnaar\b|\bdo\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:application|bewerbung|candidature|candidatura|solicitud|sollicitatie)"
        r".{0,100}(?:contact|recruiter|hiring manager|fragen|questions?|preguntas|domande)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:for\s+(?:more|further)\s+(?:details|information)|further\s+information)"
        r"\s*[:,\-–—]?\s*.{0,140}(?:available|speak\s+with|contact|recruit|"
        r"talent\s+acquisition|hiring)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:our|the)\s+(?:recruitment|recruiting|talent\s+acquisition|hiring)\s+"
        r"(?:lead|manager|contact|partner)\b.{0,100}(?:\bis\b|[:\-–—])",
        re.IGNORECASE,
    ),
)

_PROVIDER_CONTACT_CONTEXT_MARKERS = (
    "application support",
    "application contact",
    "bewerbungskontakt",
    "ansprechpartner",
    "contact person",
    "contact recrutement",
    "hiring manager",
    "hr liaison",
    "human resources",
    "people partner",
    "recruiter",
    "recruitment",
    "talent acquisition",
)
_PROVIDER_CONTACT_ACTION_MARKERS = (
    "ask ",
    "contact",
    "directed to",
    "enquir",
    "fragen",
    "happy to help",
    "help",
    " is available",
    "liaison",
    "for further details",
    "for further information",
    "for more details",
    "for more information",
    "lead is",
    "questions",
    "reach",
    "speak with",
    "talk to",
    "wenden",
)
_PROVIDER_CONTACT_LINE_START = re.compile(
    r"^\s*(?:application contact|application support|ansprechpartner(?:in)?|bewerbungskontakt|"
    r"contact person|hiring manager|hr liaison|recruitment enquiries)\s*[:\-–—]",
    re.IGNORECASE,
)
_PROVIDER_PHONE_CANDIDATE_PATTERN = re.compile(
    r"(?<![\w])(?:\+\s?\d|00\s?\d|0\d)(?:[\d\s()./-]{5,}\d)(?![\w])"
    r"|(?<![\w])\(?\d{2,4}\)?(?:[\s./-]\d{1,5}){2,5}(?![\w])"
)
_PROVIDER_DATE_OR_TIME_PATTERN = re.compile(
    r"\s*(?:\d{1,4}[./-]){2}\d{1,4}(?:\s+\d{1,2}(?::?\d{2})?)?\s*"
)
_PROVIDER_SALARY_CONTEXT_PATTERN = re.compile(
    r"(?:[€$£]|\b(?:eur|usd|gbp|salary|gross|annual|year|gehalt|jahresgehalt)\b)",
    re.IGNORECASE,
)
_PROVIDER_SALARY_RANGE_PATTERN = re.compile(
    r"\s*\d{2,3}(?:[ .]\d{3})?\s*[-–—/]\s*"
    r"\d{2,3}(?:[ .]\d{3})?\s*"
)


def _is_provider_private_contact_segment(segment: str) -> bool:
    if any(pattern.search(segment) for pattern in _PROVIDER_PRIVATE_CONTACT_PATTERNS):
        return True
    folded = " ".join(segment.casefold().split())
    return any(marker in folded for marker in _PROVIDER_CONTACT_CONTEXT_MARKERS) and any(
        marker in folded for marker in _PROVIDER_CONTACT_ACTION_MARKERS
    )


def redact_application_contact_segments(
    text: str,
    *,
    replacement: str = "[application contact kept local]",
) -> str:
    """Withhold clearly contact-shaped sentences from provider-bound text.

    This is deliberately sentence-level and fail-closed.  It complements the
    exact, evidence-backed field replacement below: extraction can remain
    conservative while a novel label cannot silently disclose a public contact
    identity to an external model.
    """

    lines = re.split(r"(\n+)", text)
    for line_index in range(0, len(lines), 2):
        line = lines[line_index]
        if not line:
            continue
        if _PROVIDER_CONTACT_LINE_START.search(line):
            lines[line_index] = replacement
            continue
        sentences = re.split(r"((?<=[.!?])\s+)", line)
        for sentence_index in range(0, len(sentences), 2):
            sentence = sentences[sentence_index]
            if sentence and _is_provider_private_contact_segment(sentence):
                sentences[sentence_index] = replacement
        lines[line_index] = "".join(sentences)
    return "".join(lines)


def redact_application_phone_numbers(
    text: str,
    *,
    replacement: str = "[application phone kept local]",
) -> str:
    """Remove phone-like groups without eating ordinary dates or salary ranges."""

    def replace(candidate: re.Match[str]) -> str:
        value = candidate.group(0)
        digits = re.sub(r"\D", "", value)
        if not 9 <= len(digits) <= 15:
            return value
        if _PROVIDER_DATE_OR_TIME_PATTERN.fullmatch(value):
            return value

        stripped = value.lstrip()
        explicit_international = stripped.startswith(("+", "00"))
        context = text[max(0, candidate.start() - 32) : candidate.end() + 32]
        if _PROVIDER_SALARY_RANGE_PATTERN.fullmatch(
            value
        ) and _PROVIDER_SALARY_CONTEXT_PATTERN.search(context):
            return value

        groups = re.findall(r"\d+", value)
        locally_plausible = stripped.startswith("0")
        visibly_grouped = len(groups) >= 3 or "(" in value
        if not (explicit_international or locally_plausible or visibly_grouped):
            return value
        return replacement

    return _PROVIDER_PHONE_CANDIDATE_PATTERN.sub(replace, text)


_DOCUMENT_PATTERNS = (
    (
        "CV",
        re.compile(
            r"\b(?:cv|curriculum vitae|lebenslauf|curr[ií]culum(?: vitae)?|życiorys)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Cover letter",
        re.compile(
            r"\b(?:anschreiben|cover letter|lettre de motivation|carta (?:de |di )?"
            r"(?:presentaci[oó]n|motivaci[oó]n)|lettera (?:di )?(?:presentazione|motivazionale)|"
            r"motivatiebrief|list motywacyjny|motivationsschreiben)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Certificates",
        re.compile(
            r"\b(?:certificat(?:e|es|s|i)?|dipl[oô]mes?|nachweise|świadectwa|zeugnisse)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Portfolio",
        re.compile(
            r"\b(?:arbeitsproben|portfolio|pr[oó]bki prac|work samples)\b",
            re.IGNORECASE,
        ),
    ),
)


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def _guidance_segments(source_text: str) -> list[tuple[str, str]]:
    """Keep exact, reviewable source spans while making dense ATS text searchable.

    JobPosting JSON-LD descriptions are often flattened into one very long line.
    Splitting only at visible sentence/bullet boundaries lets the deterministic
    pass retain verbatim provenance without treating the whole advertisement as
    one contact sentence.
    """

    segments: list[tuple[str, str]] = []
    boundary = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Þ0-9])|\s*[\u2022●▪◦]\s*|\s+\|\s+")
    for raw_line in source_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        split_parts = boundary.split(raw_line)
        parts: list[str] = []
        for part in split_parts:
            if parts and re.search(
                r"(?:\b(?:dr|prof|mr|mrs|ms|mme|m|st|ul)|\b\d{1,2})\.$",
                parts[-1].strip(),
                flags=re.IGNORECASE,
            ):
                parts[-1] = f"{parts[-1]} {part}"
            else:
                parts.append(part)
        for part in parts:
            quote = part.strip()
            if not quote:
                continue
            # A guidance entry is capped at 2,000 characters. Long unpunctuated
            # ATS blocks remain usable by taking bounded exact windows instead
            # of manufacturing normalized evidence.
            if len(quote) <= 1_900:
                segments.append((quote, " ".join(quote.split())))
                continue
            for start in range(0, len(quote), 1_800):
                window = quote[start : start + 1_800].strip()
                if window:
                    segments.append((window, " ".join(window.split())))
    return segments


def _phone_from_line(value: str) -> str | None:
    """Return a plausible published phone number, excluding dates and IDs."""

    for match in _PHONE_RE.finditer(value):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        if not 7 <= len(digits) <= 15:
            continue
        if re.fullmatch(r"\d{1,4}[./-]\d{1,2}[./-]\d{2,4}", candidate):
            continue
        return candidate
    return None


def _has_application_context(value: str) -> bool:
    folded = _fold(value)
    return any(marker in folded for marker in _APPLICATION_CONTEXT_MARKERS) or bool(
        re.search(r"\bcv\b", folded, flags=re.IGNORECASE)
    )


_APPLICATION_EMAIL_MARKERS = (
    "apply",
    "application",
    "bewerb",
    "candidat",
    "career",
    "karriere",
    "lebenslauf",
    "recruit",
    "solicitud",
    "sollicit",
    "talent",
)
_APPLICATION_EMAIL_LOCAL_PARTS = (
    "application",
    "apply",
    "bewerbung",
    "career",
    "hr",
    "job",
    "people",
    "recruit",
    "talent",
)
_NON_APPLICATION_EMAIL_MARKERS = (
    "abuse",
    "datenschutz",
    "dpo",
    "impressum",
    "legal",
    "noreply",
    "privacy",
    "security",
    "support",
)


def _preferred_application_email(
    lines: list[tuple[str, str]],
    *,
    source_url: str | None,
    contact_line_index: int | None,
) -> tuple[str, str] | None:
    """Choose the most job-specific published address, never a footer mailbox."""

    context_indices = {
        index
        for index, (_, line) in enumerate(lines)
        if any(marker in _fold(line) for marker in _APPLICATION_EMAIL_MARKERS)
        or bool(re.search(r"\bcv\b", _fold(line), flags=re.IGNORECASE))
    }
    source_host = (urlsplit(source_url).hostname or "").casefold() if source_url else ""
    candidates: list[tuple[int, int, str, str]] = []
    for index, (quote, line) in enumerate(lines):
        for match in _EMAIL_RE.finditer(line):
            email = match.group(0)
            folded_line = _fold(line)
            local_part, _, email_domain = email.casefold().partition("@")
            nearest_context = min(
                (abs(index - context_index) for context_index in context_indices),
                default=99,
            )
            score = 0
            if index in context_indices:
                score += 50
            elif nearest_context <= 2:
                score += 28
            elif nearest_context <= 5:
                score += 12
            if contact_line_index is not None and abs(index - contact_line_index) <= 3:
                score += 30
            if any(marker in local_part for marker in _APPLICATION_EMAIL_LOCAL_PARTS):
                score += 35
            if any(
                marker in folded_line
                for marker in (*_EMAIL_CHANNEL_MARKERS, "e-mail an", "email to", "email at")
            ):
                score += 35
            if source_host and (
                source_host == email_domain or source_host.endswith(f".{email_domain}")
            ):
                score += 5
            if any(
                marker in local_part or marker in folded_line
                for marker in _NON_APPLICATION_EMAIL_MARKERS
            ):
                score -= 100
            # An address without any job/application relationship is ordinary
            # company contact data, not an application destination.
            if score >= 30:
                candidates.append((score, -index, email, quote))
    if not candidates:
        return None
    _, _, email, quote = max(candidates)
    return email, quote


def _trim_contact_coordinates(value: str) -> str:
    cut_at = len(value)
    for pattern in (_EMAIL_RE, _URL_RE, _PHONE_RE):
        if match := pattern.search(value):
            cut_at = min(cut_at, match.start())
    return value[:cut_at].strip(" ,;|:-")


def _looks_like_contact_name(value: str) -> bool:
    folded = _fold(value)
    if not value or len(value) > 120 or any(character.isdigit() for character in value):
        return False
    if any(
        marker in folded
        for marker in (
            "abteilung",
            "department",
            "people & culture",
            "recruiting team",
            "recruitment team",
            "service recrutement",
            "team",
        )
    ):
        return False
    tokens = value.replace("/", " ").split()
    meaningful = [
        token
        for token in tokens
        if token.casefold().strip(".,")
        not in {
            "dr",
            "frau",
            "herr",
            "herrn",
            "m",
            "madame",
            "mme",
            "monsieur",
            "mr",
            "mrs",
            "ms",
            "prof",
            "signor",
            "signora",
        }
    ]
    return 2 <= len(meaningful) <= 6 and all(
        any(character.isalpha() for character in token) for token in meaningful
    )


def _looks_like_contact_role(value: str) -> bool:
    folded = f"{_fold(value)} "
    return (
        1 <= len(value.split()) <= 12
        and not (_EMAIL_RE.search(value) or _URL_RE.search(value) or _PHONE_RE.search(value))
        and any(marker in folded for marker in _ROLE_MARKERS)
    )


def _split_contact_body(value: str) -> tuple[str | None, str | None]:
    body = _trim_contact_coordinates(value)
    body = re.sub(
        r"\s+(?:erreichbar|available|joignable|raggiungibile)\b.*$",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip(" ,;|:-")
    body = re.sub(
        r"\s*[,;|:/-]*\s*(?:e-?mail|phone|tel\.?|telefon)\s*[:.]?\s*$",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip(" ,;|:-")
    if not body:
        return None, None

    role = None
    parenthesized = re.fullmatch(r"(.+?)\s*\(([^()]{2,120})\)\s*", body)
    if parenthesized and _looks_like_contact_role(parenthesized.group(2)):
        body, role = parenthesized.group(1), parenthesized.group(2)
    else:
        parts = re.split(r"\s*(?:,|;|\||\s[/–—-]\s)\s*", body, maxsplit=1)
        if len(parts) == 2 and _looks_like_contact_role(parts[1]):
            body, role = parts
        else:
            relation = re.fullmatch(
                r"(.+?)\s+(?:aus dem|aus unserem|from (?:the|our)|du service|"
                r"del equipo de|del team|van het)\s+(.+)",
                body,
                flags=re.IGNORECASE,
            )
            if relation and _looks_like_contact_role(relation.group(2)):
                body, role = relation.group(1), relation.group(2)

    name = " ".join(body.split()).strip(" ,;|:-")
    clean_role = role.strip(" ,;|:-.") if role else None
    return (name if _looks_like_contact_name(name) else None), clean_role


def _contact_from_line(value: str) -> tuple[str | None, str | None]:
    if match := _CONTACT_LABEL_RE.search(value):
        return _split_contact_body(match.group("body"))
    for pattern in _CONTACT_SENTENCE_PATTERNS:
        if match := pattern.search(value):
            return _split_contact_body(match.group("body"))
    return None, None


def _channel_from_line(value: str) -> ApplicationChannel | None:
    folded = _fold(value)
    if any(marker in folded for marker in _PORTAL_CHANNEL_MARKERS):
        return ApplicationChannel.EMPLOYER_PORTAL
    if any(marker in folded for marker in _EMAIL_CHANNEL_MARKERS) and _EMAIL_RE.search(value):
        return ApplicationChannel.EMAIL
    if any(marker in folded for marker in _POSTAL_CHANNEL_MARKERS):
        return ApplicationChannel.POSTAL
    return None


def _postal_address_from_lines(
    lines: list[tuple[str, str]],
    index: int,
    *,
    application_context: bool,
    contact_line_index: int | None,
) -> tuple[str, str] | None:
    """Return an explicit source-published delivery address without web enrichment."""

    quote, line = lines[index]
    label_match = _POSTAL_ADDRESS_LABEL_RE.search(line)
    near_contact = (
        contact_line_index is not None and contact_line_index < index <= contact_line_index + 4
    )
    candidates: list[tuple[str, str]] = []
    if label_match:
        body = " ".join(label_match.group("body").split()).strip(" ,;|:-")
        if body:
            # The label makes the current sentence an explicit delivery
            # coordinate. Keep the complete address (including a city between
            # street and postcode) while stopping before a same-line action.
            body = re.split(
                r"\s+(?=(?:apply|bitte|env[ií]a|envoyez|invia|please|stuur|wyślij)\b)",
                body,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].rstrip(" .,;")
            candidates.append((body, quote))
        found_address_component = False
        for next_quote, next_line in lines[index + 1 : index + 5]:
            if _STREET_ADDRESS_RE.search(next_line) or _POSTCODE_CITY_RE.search(next_line):
                candidates.append((next_line, next_quote))
                found_address_component = True
            elif not found_address_component and len(next_line) <= 120:
                # A labelled postal block often contains the company/legal
                # entity on the first line before street and locality.  It is
                # not itself a contact coordinate and therefore is skipped.
                continue
            else:
                break
    elif application_context or near_contact:
        if street_match := _STREET_CORE_RE.search(line):
            candidates.append((street_match.group(0).rstrip(".,;"), quote))
            locality_match = _POSTCODE_CITY_RE.search(line)
            if (
                locality_match
                and locality_match.group(0).casefold() not in street_match.group(0).casefold()
            ):
                candidates.append((locality_match.group(0).rstrip(".,;"), quote))
            if index + 1 < len(lines):
                next_quote, next_line = lines[index + 1]
                if _POSTCODE_CITY_RE.search(next_line):
                    candidates.append((next_line, next_quote))

    if not candidates:
        return None
    value = ", ".join(candidate for candidate, _ in candidates)
    evidence = "\n".join(dict.fromkeys(candidate_quote for _, candidate_quote in candidates))
    return value[:500], evidence[:2_000]


def _published_address_fallback(
    lines: list[tuple[str, str]],
) -> tuple[str, str] | None:
    """Return a source-published location when no application address is labelled.

    A workplace or company address is useful when preparing a letter, but it
    must not be presented as a postal application channel.  The UI therefore
    labels this fallback as a *published address*, while the channel remains
    unknown unless the advertisement explicitly requests a postal submission.
    """

    schema_values: list[str] = []
    schema_quotes: list[str] = []
    for quote, line in lines:
        for match in _SCHEMA_POSTAL_ADDRESS_RE.finditer(line):
            place = " ".join(match.group("place").split()).strip(" ,;·-")
            value = f"{match.group('postcode')} {place}, {match.group('country')}"
            if value.casefold() not in {item.casefold() for item in schema_values}:
                schema_values.append(value)
                schema_quotes.append(quote)
        if schema_values:
            # A flattened schema.org line can contain several workplaces.  In
            # that case every parsed address has the same source quote.  Keep
            # the useful distinct address values, but include that quote only
            # once so the combined evidence remains a verbatim source span.
            evidence = "\n".join(dict.fromkeys(schema_quotes))
            return " / ".join(schema_values)[:500], evidence[:2_000]

    for index, (quote, line) in enumerate(lines):
        street_match = _STREET_CORE_RE.search(line)
        if street_match is None:
            continue
        parts = [street_match.group(0).rstrip(".,;")]
        evidence = [quote]
        locality_match = _POSTCODE_CITY_RE.search(line)
        if locality_match is not None:
            locality = locality_match.group(0).rstrip(".,;")
            if locality.casefold() not in parts[0].casefold():
                parts.append(locality)
        elif index + 1 < len(lines):
            next_quote, next_line = lines[index + 1]
            locality_match = _POSTCODE_CITY_RE.search(next_line)
            if locality_match is not None:
                parts.append(locality_match.group(0).rstrip(".,;"))
                evidence.append(next_quote)
        return ", ".join(parts)[:500], "\n".join(dict.fromkeys(evidence))[:2_000]
    return None


def extract_application_guidance(
    source_text: str,
    *,
    source_url: str | None = None,
    include_published_address: bool = True,
) -> ApplicationGuidance:
    """Conservatively extract explicit application logistics from European postings.

    This deterministic pass intentionally recognizes only obvious labels and
    application sentences.  Values remain source-attributed and can be reviewed
    locally; nothing here authorizes sending contact data to an LLM.
    """

    lines = _guidance_segments(source_text)
    contact_name = None
    contact_role = None
    contact_email = None
    contact_phone = None
    postal_address = None
    channel = None
    application_url = None
    documents: list[ApplicationGuidanceEntry] = []
    max_file_size = None
    max_pages = None
    deadline = None
    instructions: list[ApplicationGuidanceEntry] = []

    def entry(value: str, quote: str) -> ApplicationGuidanceEntry:
        return ApplicationGuidanceEntry(
            value=" ".join(value.split()),
            evidence_quote=quote,
            source_url=source_url,
        )

    contact_line_index = None
    postal_context_line_index = None
    application_context_line_index = None
    for index, (quote, line) in enumerate(lines):
        folded = _fold(line)
        if _has_application_context(line):
            application_context_line_index = index
        if any(marker in folded for marker in _POSTAL_DELIVERY_MARKERS):
            postal_context_line_index = index
        application_context = (
            _has_application_context(line)
            or (index > 0 and _has_application_context(lines[index - 1][1]))
            or (
                application_context_line_index is not None
                and application_context_line_index < index <= application_context_line_index + 5
            )
            or (
                contact_line_index is not None
                and contact_line_index < index <= contact_line_index + 3
            )
        )
        if application_context and application_url is None:
            match = _URL_RE.search(line)
            if match:
                clean_url = match.group(0).rstrip(".,;:)]}")
                application_url = entry(clean_url, clean_url)

        if contact_name is None:
            proposed_name, proposed_role = _contact_from_line(line)
            if proposed_name is not None:
                contact_name = entry(proposed_name, quote)
                contact_line_index = index
                if proposed_role is not None:
                    contact_role = entry(proposed_role, quote)
            elif _CONTACT_HEADING_RE.fullmatch(line.rstrip(" :|-–—")) and index + 1 < len(lines):
                next_quote, next_line = lines[index + 1]
                proposed_name, proposed_role = _split_contact_body(next_line)
                if proposed_name is not None:
                    contact_name = entry(proposed_name, next_quote)
                    contact_line_index = index + 1
                    if proposed_role is not None:
                        contact_role = entry(proposed_role, next_quote)

        if (
            contact_name is not None
            and contact_role is None
            and contact_line_index is not None
            and index == contact_line_index + 1
            and _looks_like_contact_role(line)
        ):
            contact_role = entry(line, quote)

        if contact_phone is None and application_context:
            if phone := _phone_from_line(line):
                contact_phone = entry(phone, phone)

        if postal_address is None:
            detected_address = _postal_address_from_lines(
                lines,
                index,
                application_context=(
                    application_context
                    or (
                        postal_context_line_index is not None
                        and postal_context_line_index < index <= postal_context_line_index + 4
                    )
                ),
                contact_line_index=contact_line_index,
            )
            if detected_address is not None:
                address_value, address_quote = detected_address
                postal_address = entry(address_value, address_quote)

        if channel is None:
            if detected_channel := _channel_from_line(line):
                channel = entry(detected_channel.value, quote)
        elif (
            channel.value != ApplicationChannel.EMPLOYER_PORTAL.value
            and _channel_from_line(line) == ApplicationChannel.EMPLOYER_PORTAL
        ):
            channel = entry(ApplicationChannel.EMPLOYER_PORTAL.value, quote)

        if application_context:
            for label, pattern in _DOCUMENT_PATTERNS:
                document_match = pattern.search(line)
                if document_match and all(
                    not item.value.casefold().startswith(label.casefold()) for item in documents
                ):
                    nearby = line[
                        max(0, document_match.start() - 45) : document_match.end() + 55
                    ].casefold()
                    explicitly_not_requested = label == "Cover letter" and any(
                        marker in nearby
                        for marker in (
                            "kein anschreiben",
                            "anschreiben nicht erforderlich",
                            "without a cover letter",
                            "no cover letter",
                            "sans lettre de motivation",
                            "sin carta de motivación",
                            "senza lettera motivazionale",
                        )
                    )
                    optional = label == "Cover letter" and any(
                        marker in nearby
                        for marker in (
                            "nicht zwingend",
                            "optional",
                            "facultatif",
                            "facultative",
                            "opcional",
                            "facoltativ",
                        )
                    )
                    if explicitly_not_requested:
                        continue
                    documents.append(entry(f"{label} (optional)" if optional else label, quote))

        if (
            max_file_size is None
            and application_context
            and any(
                marker in folded
                for marker in (
                    "anhang",
                    "attachment",
                    "datei",
                    "document",
                    "fichier",
                    "file",
                    "pièce jointe",
                    "plik",
                    "unterlagen",
                    "upload",
                )
            )
        ):
            match = re.search(r"\d+(?:[.,]\d+)?\s*(?:mb|mib)", line, flags=re.IGNORECASE)
            if match:
                max_file_size = entry(match.group(0), quote)
        if max_pages is None:
            match = re.search(
                r"(?:maximum|max\.?|maximal|höchstens|bis zu|nicht mehr als|no more than|"
                r"up to|au maximum|pas plus de|massimo|non più di|como máximo|"
                r"máximo|maksymalnie)\s*(\d+)\s*(?:pages?|seiten?|pagine|páginas?|stron)",
                line,
                flags=re.IGNORECASE,
            )
            if match is None:
                match = re.search(
                    r"(?:a |ein(?:e|en)? |une? |una? )?(\d+)[- ](?:page|seit|pagin|stron)"
                    r"[\w-]{0,20}(?:cv|lebenslauf|anschreiben|letter|document)",
                    line,
                    flags=re.IGNORECASE,
                )
            if match:
                max_pages = entry(match.group(1), quote)
        if deadline is None and any(
            marker in folded
            for marker in (
                "bewerbungsfrist",
                "deadline",
                "application closes",
                "bewerbungsschluss",
                "bewerben bis",
                "apply by",
                "date limite",
                "fecha límite",
                "scadenza",
                "sluitingsdatum",
                "termin składania",
            )
        ):
            deadline = entry(line[:200], quote)
        if (
            application_context
            and any(marker in folded for marker in (*_INSTRUCTION_MARKERS, *_PROCESS_MARKERS))
            and len(instructions) < 8
            and all(item.value.casefold() != line.casefold() for item in instructions)
        ):
            instructions.append(entry(line[:1_000], quote))

    preferred_email = _preferred_application_email(
        lines,
        source_url=source_url,
        contact_line_index=contact_line_index,
    )
    if preferred_email is not None:
        email_value, email_quote = preferred_email
        contact_email = entry(email_value, email_quote)

    if postal_address is None and include_published_address:
        published_address = _published_address_fallback(lines)
        if published_address is not None:
            address_value, address_quote = published_address
            postal_address = entry(address_value, address_quote)

    return ApplicationGuidance(
        contact_name=contact_name,
        contact_role=contact_role,
        contact_email=contact_email,
        contact_phone=contact_phone,
        postal_address=postal_address,
        application_channel=channel,
        application_url=application_url,
        requested_documents=tuple(documents),
        max_file_size=max_file_size,
        max_pages=max_pages,
        application_deadline=deadline,
        instructions=tuple(instructions),
    )


def merge_application_guidance(
    deterministic: ApplicationGuidance,
    model: ApplicationGuidance,
) -> ApplicationGuidance:
    """Prefer verified model fields, retaining unique deterministic list evidence."""

    update = {}
    for field in (
        "contact_name",
        "contact_role",
        "contact_email",
        "contact_phone",
        "postal_address",
        "application_channel",
        "application_url",
        "max_file_size",
        "max_pages",
        "application_deadline",
    ):
        if field == "contact_email":
            # The deterministic pass ranks every source-published mailbox and
            # can distinguish an explicit application address from a generic
            # support/privacy footer. Prefer that result over legacy model
            # guidance, while retaining a verified model-only value as a
            # backwards-compatible fallback.
            update[field] = getattr(deterministic, field) or getattr(model, field)
        else:
            update[field] = getattr(model, field) or getattr(deterministic, field)
    postal_address = update["postal_address"]
    if postal_address is not None:
        clean_address = _clean_merged_postal_address(postal_address.value)
        if clean_address and clean_address != postal_address.value:
            update["postal_address"] = postal_address.model_copy(update={"value": clean_address})
    for field in ("requested_documents", "instructions"):
        combined = []
        seen = set()
        for item in (*getattr(model, field), *getattr(deterministic, field)):
            key = item.value.casefold()
            if key not in seen:
                seen.add(key)
                combined.append(item)
        update[field] = tuple(combined)
    return ApplicationGuidance(**update)


def _clean_merged_postal_address(value: str) -> str:
    """Remove schema labels and collapse a repeated representation of one address.

    Older model output could concatenate its formatted address with the same
    schema.org ``PostalAddress`` block.  Keeping both made the job-detail tile
    look like two published destinations.  Distinct workplace addresses remain
    untouched; only segments sharing both a street/house number and postcode
    are treated as the same address.
    """

    label = re.compile(
        r"\s*(?:postal\s*address|postaladdress|postanschrift)\s*[:|\-–—]?\s*",
        flags=re.IGNORECASE,
    )
    parts = [" ".join(part.split()).strip(" ,;|/-–—") for part in label.split(value)]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    def identity(part: str) -> tuple[str | None, str | None]:
        street_match = _STREET_CORE_RE.search(part)
        postcode_match = re.search(r"\b\d{4,6}\b", part)
        street = re.sub(r"\W+", "", street_match.group(0).casefold()) if street_match else None
        postcode = postcode_match.group(0) if postcode_match else None
        return street, postcode

    identities = [identity(part) for part in parts]
    first_street, first_postcode = identities[0]
    if (
        first_street
        and first_postcode
        and all(
            street == first_street and postcode == first_postcode
            for street, postcode in identities[1:]
        )
    ):
        # Prefer the representation carrying the most useful locality tokens.
        return max(parts, key=lambda part: (len(part.split()), len(part)))
    return " / ".join(dict.fromkeys(parts))
