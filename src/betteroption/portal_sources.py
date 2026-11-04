"""Persona-owned employer career portals used as bounded Explore hints."""

from __future__ import annotations

import ipaddress
import socket
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .personas import AccountPersonaRow
from .profile import StrictModel


MAX_PORTAL_SOURCES = 10
MAX_PORTAL_LABEL_LENGTH = 80


class PortalSourceError(ValueError):
    """Raised when a persona portal source is invalid or outside its owner boundary."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _default_resolver(host: str) -> list[str]:
    return list(
        {address[4][0] for address in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    )


def normalize_portal_url(
    value: str,
    *,
    resolver: Callable[[str], list[str]] = _default_resolver,
) -> tuple[str, str]:
    """Return a stable HTTPS portal URL and public hostname.

    The portal is never crawled directly.  DNS validation still rejects local,
    private, link-local, multicast, and reserved targets before its hostname can
    be passed to a configured search provider.
    """

    raw = value.strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise PortalSourceError("Enter a valid public HTTPS career-portal URL.") from exc
    if parsed.scheme.casefold() != "https":
        raise PortalSourceError("Career portal URLs must use HTTPS.")
    try:
        port = parsed.port
        host = (parsed.hostname or "").encode("idna").decode("ascii").casefold().rstrip(".")
    except (UnicodeError, ValueError) as exc:
        raise PortalSourceError("Enter a valid public HTTPS career-portal URL.") from exc
    if not host or parsed.username or parsed.password or port not in {None, 443}:
        raise PortalSourceError("Use a public HTTPS URL without credentials or a custom port.")
    try:
        addresses = resolver(host)
    except OSError as exc:
        raise PortalSourceError("The career portal host could not be resolved.") from exc
    if not addresses:
        raise PortalSourceError("The career portal host resolved to no public address.")
    for address in addresses:
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError as exc:
            raise PortalSourceError("The career portal resolved to an invalid address.") from exc
        if not resolved.is_global:
            raise PortalSourceError(
                "Private, local, and reserved career-portal targets are blocked."
            )
    path = parsed.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, "", "")), host


def normalize_portal_label(value: str, *, fallback: str) -> str:
    label = " ".join(unicodedata.normalize("NFKC", value).split()) or fallback
    if len(label) > MAX_PORTAL_LABEL_LENGTH:
        raise PortalSourceError(
            f"Use at most {MAX_PORTAL_LABEL_LENGTH} characters for a portal label."
        )
    if any(unicodedata.category(character).startswith("C") for character in label):
        raise PortalSourceError("The portal label contains unsupported control characters.")
    return label


def portal_search_scope(portal_url: str) -> str:
    """Keep a career locale/branch but remove generic search landing leaves."""

    parsed = urlsplit(portal_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[-1].casefold() in {
        "search",
        "searchjobs",
        "search-jobs",
        "job-search",
        "jobsearch",
    }:
        parts.pop()
    path = f"/{'/'.join(parts)}" if parts else ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class PersonaPortalSourceRow(Base):
    __tablename__ = "persona_portal_sources"
    __table_args__ = (
        UniqueConstraint(
            "persona_id",
            "portal_url",
            name="uq_persona_portal_sources_persona_url",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    persona_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(MAX_PORTAL_LABEL_LENGTH), nullable=False)
    portal_url: Mapped[str] = mapped_column(String(2_000), nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonaPortalSource(StrictModel):
    id: UUID
    persona_id: UUID
    label: str
    portal_url: str
    hostname: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PortalSourceRepository:
    def __init__(
        self,
        database: Database,
        *,
        resolver: Callable[[str], list[str]] = _default_resolver,
    ) -> None:
        self.database = database
        self.session_factory = database.session_factory
        self.resolver = resolver

    @staticmethod
    def _to_source(row: PersonaPortalSourceRow) -> PersonaPortalSource:
        return PersonaPortalSource(
            id=UUID(row.id),
            persona_id=UUID(row.persona_id),
            label=row.label,
            portal_url=row.portal_url,
            hostname=row.hostname,
            enabled=row.enabled,
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    @staticmethod
    def _owned_persona(session, persona_id: UUID, account_id: UUID) -> AccountPersonaRow:
        persona = session.get(AccountPersonaRow, str(persona_id))
        if persona is None or persona.account_id != str(account_id):
            raise PortalSourceError("Persona not found.")
        return persona

    def list_for_persona(
        self,
        persona_id: UUID,
        *,
        account_id: UUID,
    ) -> list[PersonaPortalSource]:
        with self.session_factory() as session:
            self._owned_persona(session, persona_id, account_id)
            rows = session.scalars(
                select(PersonaPortalSourceRow)
                .where(PersonaPortalSourceRow.persona_id == str(persona_id))
                .order_by(
                    PersonaPortalSourceRow.created_at.asc(),
                    PersonaPortalSourceRow.id.asc(),
                )
            ).all()
            return [self._to_source(row) for row in rows]

    def enabled_hostnames(
        self,
        persona_id: UUID,
        *,
        account_id: UUID,
    ) -> list[str]:
        return [
            source.hostname
            for source in self.list_for_persona(persona_id, account_id=account_id)
            if source.enabled
        ]

    def enabled_portal_urls(
        self,
        persona_id: UUID,
        *,
        account_id: UUID,
    ) -> list[str]:
        """Return validated full scopes, preserving a saved locale/path."""

        return [
            portal_search_scope(source.portal_url)
            for source in self.list_for_persona(persona_id, account_id=account_id)
            if source.enabled
        ]

    def create(
        self,
        persona_id: UUID,
        *,
        account_id: UUID,
        url: str,
        label: str = "",
        maximum_sources: int = MAX_PORTAL_SOURCES,
    ) -> PersonaPortalSource:
        portal_url, hostname = normalize_portal_url(url, resolver=self.resolver)
        clean_label = normalize_portal_label(label, fallback=hostname.removeprefix("www."))
        now = utc_now()
        try:
            with self.session_factory.begin() as session:
                self._owned_persona(session, persona_id, account_id)
                count = int(
                    session.scalar(
                        select(func.count(PersonaPortalSourceRow.id)).where(
                            PersonaPortalSourceRow.persona_id == str(persona_id)
                        )
                    )
                    or 0
                )
                if count >= maximum_sources:
                    raise PortalSourceError(
                        f"This persona can keep up to {maximum_sources} employer portals."
                    )
                row = PersonaPortalSourceRow(
                    id=str(uuid4()),
                    persona_id=str(persona_id),
                    label=clean_label,
                    portal_url=portal_url,
                    hostname=hostname,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.flush()
                return self._to_source(row)
        except IntegrityError as exc:
            raise PortalSourceError(
                "That employer portal is already saved for this persona."
            ) from exc

    def set_enabled(
        self,
        source_id: UUID,
        *,
        account_id: UUID,
        persona_id: UUID,
        enabled: bool,
    ) -> PersonaPortalSource:
        with self.session_factory.begin() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.get(PersonaPortalSourceRow, str(source_id))
            if row is None or row.persona_id != str(persona_id):
                raise PortalSourceError("Employer portal not found.")
            row.enabled = enabled
            row.updated_at = utc_now()
            session.flush()
            return self._to_source(row)

    def delete(
        self,
        source_id: UUID,
        *,
        account_id: UUID,
        persona_id: UUID,
    ) -> bool:
        with self.session_factory.begin() as session:
            self._owned_persona(session, persona_id, account_id)
            row = session.get(PersonaPortalSourceRow, str(source_id))
            if row is None or row.persona_id != str(persona_id):
                raise PortalSourceError("Employer portal not found.")
            session.delete(row)
            return True
