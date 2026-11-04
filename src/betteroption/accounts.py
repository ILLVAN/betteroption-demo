"""Accounts, password authentication, and opaque browser sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, Database
from .job_repository import JobRecordRow
from .profile import StrictModel
from .profile_repository import ProfileWorkspaceRow
from .result_repository import ResultAccessGrantRow

USERNAME_MAX_LENGTH = 32


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RegistrationMode(StrEnum):
    FIRST_USER = "first_user"
    OPEN = "open"
    INVITE_ONLY = "invite_only"
    DISABLED = "disabled"


class AccountRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class AccountAccessTier(StrEnum):
    STANDARD = "standard"
    TESTER = "tester"


class AccountRow(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), nullable=False)
    username_normalized: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AccountRole.MEMBER.value,
    )
    access_tier: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AccountAccessTier.STANDARD.value,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountBootstrapRow(Base):
    """Singleton row which serializes first-owner creation on every database."""

    __tablename__ = "account_bootstrap"
    __table_args__ = (CheckConstraint("id = 1", name="ck_account_bootstrap_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    active_persona_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("account_personas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class AccountInvitationRow(Base):
    __tablename__ = "account_invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetRow(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthAttemptRow(Base):
    __tablename__ = "auth_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Account(StrictModel):
    id: UUID
    email: str
    display_name: str
    role: AccountRole = AccountRole.MEMBER
    access_tier: AccountAccessTier = AccountAccessTier.STANDARD
    email_verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_admin(self) -> bool:
        return self.role == AccountRole.ADMIN

    @property
    def is_tester(self) -> bool:
        return self.access_tier == AccountAccessTier.TESTER


class AccountSession(StrictModel):
    token: str
    account: Account
    expires_at: datetime


class AccountInvitation(StrictModel):
    id: UUID
    email: str
    invited_by_account_id: UUID
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def pending(self) -> bool:
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > utc_now()


class AccountError(ValueError):
    """Raised when an account action is invalid or not permitted."""


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise AccountError("Enter a valid email address.")
    if len(email) > 320:
        raise AccountError("That email address is too long.")
    return email


def normalize_username(value: str) -> tuple[str, str]:
    """Return a safe display value and its case-insensitive uniqueness key."""

    display = " ".join(unicodedata.normalize("NFKC", value).split())
    if not display:
        raise AccountError("Enter a username.")
    if len(display) > USERNAME_MAX_LENGTH:
        raise AccountError(f"Use at most {USERNAME_MAX_LENGTH} characters for your username.")
    if any(unicodedata.category(character).startswith("C") for character in display):
        raise AccountError("That username contains unsupported control characters.")
    return display, display.casefold()


def _password_hash(password: str) -> str:
    if len(password) < 10:
        raise AccountError("Use at least 10 characters for your password.")
    if len(password) > 1_024:
        raise AccountError("That password is too long.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return "scrypt$16384$8$1${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_value, expected_value = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class AccountRepository:
    """Persist accounts while storing only password and session-token hashes."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.session_factory = database.session_factory

    @staticmethod
    def _to_account(row: AccountRow) -> Account:
        return Account(
            id=UUID(row.id),
            email=row.email,
            display_name=row.display_name,
            role=AccountRole(row.role),
            access_tier=AccountAccessTier(row.access_tier),
            email_verified_at=(
                ensure_utc(row.email_verified_at) if row.email_verified_at else None
            ),
            created_at=ensure_utc(row.created_at),
            updated_at=ensure_utc(row.updated_at),
        )

    @staticmethod
    def _to_invitation(row: AccountInvitationRow) -> AccountInvitation:
        return AccountInvitation(
            id=UUID(row.id),
            email=row.email,
            invited_by_account_id=UUID(row.invited_by_account_id),
            created_at=ensure_utc(row.created_at),
            expires_at=ensure_utc(row.expires_at),
            accepted_at=ensure_utc(row.accepted_at) if row.accepted_at else None,
            revoked_at=ensure_utc(row.revoked_at) if row.revoked_at else None,
        )

    def count(self) -> int:
        with self.session_factory() as database_session:
            return int(database_session.scalar(select(func.count(AccountRow.id))) or 0)

    def admin_count(self) -> int:
        with self.session_factory() as database_session:
            return int(
                database_session.scalar(
                    select(func.count(AccountRow.id)).where(
                        AccountRow.role == AccountRole.ADMIN.value
                    )
                )
                or 0
            )

    def has_operator_access(
        self,
        account: Account | None,
        *,
        legacy_operator_emails: frozenset[str] = frozenset(),
    ) -> bool:
        """Authorize DB admins, with a one-way bridge for pre-role installations.

        The environment allowlist is consulted only while the database has no
        admin. As soon as an allowlisted legacy operator promotes an account,
        database roles become the sole source of operator authority.
        """

        if account is None:
            return False
        persisted = self.get(account.id)
        if persisted is None:
            return False
        if persisted.is_admin:
            return True
        return self.admin_count() == 0 and persisted.email.casefold() in legacy_operator_emails

    def get(self, account_id: UUID) -> Account | None:
        with self.session_factory() as database_session:
            row = database_session.get(AccountRow, str(account_id))
            return self._to_account(row) if row else None

    def by_email(self, email: str) -> Account | None:
        normalized = normalize_email(email)
        with self.session_factory() as database_session:
            row = database_session.scalar(select(AccountRow).where(AccountRow.email == normalized))
            return self._to_account(row) if row else None

    def by_username(self, username: str) -> Account | None:
        _, normalized = normalize_username(username)
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(AccountRow).where(AccountRow.username_normalized == normalized)
            )
            return self._to_account(row) if row else None

    def create(
        self,
        email: str,
        display_name: str,
        password: str,
        *,
        registration_mode: RegistrationMode,
    ) -> Account:
        normalized = normalize_email(email)
        clean_name, normalized_username = normalize_username(display_name)
        password_hash = _password_hash(password)
        now = utc_now()
        try:
            with self.session_factory.begin() as database_session:
                bootstrap = database_session.scalar(
                    select(AccountBootstrapRow).where(AccountBootstrapRow.id == 1).with_for_update()
                )
                if bootstrap is None:
                    bootstrap = AccountBootstrapRow(id=1, owner_account_id=None)
                    database_session.add(bootstrap)
                    database_session.flush()
                account_count = int(database_session.scalar(select(func.count(AccountRow.id))) or 0)
                if registration_mode in {
                    RegistrationMode.DISABLED,
                    RegistrationMode.INVITE_ONLY,
                }:
                    raise AccountError("Account registration is disabled.")
                first_owner_available = account_count == 0 and bootstrap.owner_account_id is None
                if registration_mode == RegistrationMode.FIRST_USER and not first_owner_available:
                    raise AccountError(
                        "The private workspace already has an owner. Sign in instead."
                    )
                if database_session.scalar(
                    select(AccountRow.id).where(AccountRow.email == normalized)
                ):
                    raise AccountError("An account with that email address already exists.")
                if database_session.scalar(
                    select(AccountRow.id).where(
                        AccountRow.username_normalized == normalized_username
                    )
                ):
                    raise AccountError("That username is already in use.")
                row = AccountRow(
                    id=str(uuid4()),
                    email=normalized,
                    display_name=clean_name,
                    username_normalized=normalized_username,
                    password_hash=password_hash,
                    role=AccountRole.MEMBER.value,
                    access_tier=AccountAccessTier.STANDARD.value,
                    email_verified_at=now,
                    created_at=now,
                    updated_at=now,
                )
                database_session.add(row)
                database_session.flush()
                if first_owner_available:
                    claim = database_session.execute(
                        update(AccountBootstrapRow)
                        .where(
                            AccountBootstrapRow.id == 1,
                            AccountBootstrapRow.owner_account_id.is_(None),
                        )
                        .values(owner_account_id=row.id)
                    )
                    if claim.rowcount == 1:
                        row.role = AccountRole.ADMIN.value
                    elif registration_mode == RegistrationMode.FIRST_USER:
                        raise AccountError(
                            "The private workspace already has an owner. Sign in instead."
                        )
                if account_count == 0:
                    self._claim_legacy_data(database_session, row.id, now)
                database_session.flush()
                return self._to_account(row)
        except IntegrityError as exc:
            if registration_mode == RegistrationMode.FIRST_USER:
                raise AccountError(
                    "The private workspace already has an owner. Sign in instead."
                ) from exc
            raise AccountError("That email address or username is already in use.") from exc

    def list_accounts(self) -> list[Account]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(AccountRow).order_by(AccountRow.created_at.asc())
            ).all()
            return [self._to_account(row) for row in rows]

    def update_access(
        self,
        account_id: UUID,
        *,
        role: AccountRole,
        access_tier: AccountAccessTier,
    ) -> Account:
        """Update product access while ensuring at least one admin remains."""

        now = utc_now()
        with self.session_factory.begin() as database_session:
            row = database_session.scalar(
                select(AccountRow).where(AccountRow.id == str(account_id)).with_for_update()
            )
            if row is None:
                raise AccountError("Account not found.")
            if row.role == AccountRole.ADMIN.value and role != AccountRole.ADMIN:
                admin_ids = database_session.scalars(
                    select(AccountRow.id)
                    .where(AccountRow.role == AccountRole.ADMIN.value)
                    .with_for_update()
                ).all()
                if len(admin_ids) <= 1:
                    raise AccountError("Promote another admin before removing the last admin.")
            row.role = role.value
            row.access_tier = access_tier.value
            row.updated_at = now
            database_session.flush()
            return self._to_account(row)

    def create_invitation(
        self,
        email: str,
        *,
        invited_by_account_id: UUID,
        ttl: timedelta,
    ) -> tuple[AccountInvitation, str]:
        normalized = normalize_email(email)
        now = utc_now()
        token = secrets.token_urlsafe(32)
        with self.session_factory.begin() as database_session:
            if database_session.scalar(select(AccountRow.id).where(AccountRow.email == normalized)):
                raise AccountError("An account with that email address already exists.")
            previous = database_session.scalars(
                select(AccountInvitationRow).where(
                    AccountInvitationRow.email == normalized,
                    AccountInvitationRow.accepted_at.is_(None),
                    AccountInvitationRow.revoked_at.is_(None),
                )
            ).all()
            for invitation in previous:
                invitation.revoked_at = now
            row = AccountInvitationRow(
                id=str(uuid4()),
                email=normalized,
                token_hash=_token_hash(token),
                invited_by_account_id=str(invited_by_account_id),
                created_at=now,
                expires_at=now + ttl,
                accepted_at=None,
                revoked_at=None,
            )
            database_session.add(row)
            database_session.flush()
            return self._to_invitation(row), token

    def list_invitations(self, *, limit: int = 100) -> list[AccountInvitation]:
        with self.session_factory() as database_session:
            rows = database_session.scalars(
                select(AccountInvitationRow)
                .order_by(AccountInvitationRow.created_at.desc())
                .limit(limit)
            ).all()
            return [self._to_invitation(row) for row in rows]

    def invitation_for_token(self, token: str) -> AccountInvitation | None:
        now = utc_now()
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(AccountInvitationRow).where(
                    AccountInvitationRow.token_hash == _token_hash(token),
                    AccountInvitationRow.accepted_at.is_(None),
                    AccountInvitationRow.revoked_at.is_(None),
                    AccountInvitationRow.expires_at > now,
                )
            )
            return self._to_invitation(row) if row else None

    def revoke_invitation(self, invitation_id: UUID) -> bool:
        with self.session_factory.begin() as database_session:
            row = database_session.get(AccountInvitationRow, str(invitation_id))
            if row is None or row.accepted_at is not None or row.revoked_at is not None:
                return False
            row.revoked_at = utc_now()
            return True

    def accept_invitation(
        self,
        token: str,
        display_name: str,
        password: str,
    ) -> Account:
        clean_name, normalized_username = normalize_username(display_name)
        password_hash = _password_hash(password)
        now = utc_now()
        try:
            with self.session_factory.begin() as database_session:
                invitation = database_session.scalar(
                    select(AccountInvitationRow).where(
                        AccountInvitationRow.token_hash == _token_hash(token),
                        AccountInvitationRow.accepted_at.is_(None),
                        AccountInvitationRow.revoked_at.is_(None),
                        AccountInvitationRow.expires_at > now,
                    )
                )
                if invitation is None:
                    raise AccountError("That invitation is invalid, expired, or already used.")
                if database_session.scalar(
                    select(AccountRow.id).where(AccountRow.email == invitation.email)
                ):
                    raise AccountError("An account with that email address already exists.")
                if database_session.scalar(
                    select(AccountRow.id).where(
                        AccountRow.username_normalized == normalized_username
                    )
                ):
                    raise AccountError("That username is already in use.")
                row = AccountRow(
                    id=str(uuid4()),
                    email=invitation.email,
                    display_name=clean_name,
                    username_normalized=normalized_username,
                    password_hash=password_hash,
                    role=AccountRole.MEMBER.value,
                    access_tier=AccountAccessTier.STANDARD.value,
                    email_verified_at=now,
                    created_at=now,
                    updated_at=now,
                )
                database_session.add(row)
                invitation.accepted_at = now
                database_session.flush()
                return self._to_account(row)
        except IntegrityError as exc:
            raise AccountError("That email address or username is already in use.") from exc

    def create_password_reset(
        self,
        account_id: UUID,
        *,
        ttl: timedelta,
    ) -> tuple[Account, str]:
        now = utc_now()
        token = secrets.token_urlsafe(32)
        with self.session_factory.begin() as database_session:
            account = database_session.get(AccountRow, str(account_id))
            if account is None:
                raise AccountError("Account not found.")
            old_rows = database_session.scalars(
                select(PasswordResetRow).where(
                    PasswordResetRow.account_id == str(account_id),
                    PasswordResetRow.used_at.is_(None),
                )
            ).all()
            for old_row in old_rows:
                old_row.used_at = now
            database_session.add(
                PasswordResetRow(
                    id=str(uuid4()),
                    account_id=str(account_id),
                    token_hash=_token_hash(token),
                    created_at=now,
                    expires_at=now + ttl,
                    used_at=None,
                )
            )
            return self._to_account(account), token

    def reset_password(self, token: str, new_password: str) -> Account:
        password_hash = _password_hash(new_password)
        now = utc_now()
        with self.session_factory.begin() as database_session:
            reset = database_session.scalar(
                select(PasswordResetRow).where(
                    PasswordResetRow.token_hash == _token_hash(token),
                    PasswordResetRow.used_at.is_(None),
                    PasswordResetRow.expires_at > now,
                )
            )
            if reset is None:
                raise AccountError("That recovery link is invalid, expired, or already used.")
            account = database_session.get(AccountRow, reset.account_id)
            if account is None:
                raise AccountError("Account not found.")
            account.password_hash = password_hash
            account.updated_at = now
            reset.used_at = now
            database_session.execute(
                delete(AuthSessionRow).where(AuthSessionRow.account_id == account.id)
            )
            return self._to_account(account)

    def password_reset_account(self, token: str) -> Account | None:
        """Resolve an active reset token without exposing or consuming it."""

        now = utc_now()
        with self.session_factory() as database_session:
            reset = database_session.scalar(
                select(PasswordResetRow).where(
                    PasswordResetRow.token_hash == _token_hash(token),
                    PasswordResetRow.used_at.is_(None),
                    PasswordResetRow.expires_at > now,
                )
            )
            if reset is None:
                return None
            account = database_session.get(AccountRow, reset.account_id)
            return self._to_account(account) if account else None

    def allow_auth_attempt(
        self,
        action: str,
        subject: str,
        *,
        secret: str,
        maximum: int,
        window: timedelta,
    ) -> bool:
        """Record and bound an auth action without retaining an email or IP address."""

        now = utc_now()
        cutoff = now - window
        subject_hash = hmac.new(
            secret.encode("utf-8"),
            subject.strip().casefold().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        with self.session_factory.begin() as database_session:
            database_session.execute(
                delete(AuthAttemptRow).where(AuthAttemptRow.created_at < cutoff)
            )
            count = int(
                database_session.scalar(
                    select(func.count(AuthAttemptRow.id)).where(
                        AuthAttemptRow.action == action,
                        AuthAttemptRow.subject_hash == subject_hash,
                        AuthAttemptRow.created_at >= cutoff,
                    )
                )
                or 0
            )
            if count >= maximum:
                return False
            database_session.add(
                AuthAttemptRow(
                    id=str(uuid4()),
                    action=action,
                    subject_hash=subject_hash,
                    created_at=now,
                )
            )
            return True

    @staticmethod
    def _claim_legacy_data(database_session, account_id: str, now: datetime) -> None:
        legacy_rows = database_session.scalars(
            select(ProfileWorkspaceRow).where(ProfileWorkspaceRow.account_id.is_(None))
        ).all()
        record_ids = database_session.scalars(select(JobRecordRow.id)).all()
        for workspace in legacy_rows:
            workspace.account_id = account_id
            existing = set(
                database_session.scalars(
                    select(ResultAccessGrantRow.job_record_id).where(
                        ResultAccessGrantRow.workspace_id == workspace.id
                    )
                ).all()
            )
            for record_id in record_ids:
                if record_id not in existing:
                    database_session.add(
                        ResultAccessGrantRow(
                            workspace_id=workspace.id,
                            job_record_id=record_id,
                            granted_at=now,
                        )
                    )

    def authenticate(self, email: str, password: str) -> Account | None:
        try:
            normalized = normalize_email(email)
        except AccountError:
            return None
        with self.session_factory() as database_session:
            row = database_session.scalar(select(AccountRow).where(AccountRow.email == normalized))
            if (
                row is None
                or row.email_verified_at is None
                or not _password_matches(password, row.password_hash)
            ):
                return None
            return self._to_account(row)

    def verify_password(self, account_id: UUID, password: str) -> bool:
        with self.session_factory() as database_session:
            row = database_session.get(AccountRow, str(account_id))
            return bool(row and _password_matches(password, row.password_hash))

    def update_username(
        self,
        account_id: UUID,
        username: str,
        *,
        current_password: str,
    ) -> Account:
        display, normalized = normalize_username(username)
        try:
            with self.session_factory.begin() as database_session:
                row = database_session.get(AccountRow, str(account_id))
                if row is None:
                    raise AccountError("Account not found.")
                if not _password_matches(current_password, row.password_hash):
                    raise AccountError("The current password was not correct.")
                existing = database_session.scalar(
                    select(AccountRow.id).where(
                        AccountRow.username_normalized == normalized,
                        AccountRow.id != str(account_id),
                    )
                )
                if existing:
                    raise AccountError("That username is already in use.")
                row.display_name = display
                row.username_normalized = normalized
                row.updated_at = utc_now()
                database_session.flush()
                return self._to_account(row)
        except IntegrityError as exc:
            raise AccountError("That username is already in use.") from exc

    def change_password(
        self,
        account_id: UUID,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        password_hash = _password_hash(new_password)
        with self.session_factory.begin() as database_session:
            row = database_session.get(AccountRow, str(account_id))
            if row is None:
                raise AccountError("Account not found.")
            if not _password_matches(current_password, row.password_hash):
                raise AccountError("The current password was not correct.")
            row.password_hash = password_hash
            row.updated_at = utc_now()
            database_session.execute(
                delete(AuthSessionRow).where(AuthSessionRow.account_id == str(account_id))
            )

    def create_session(self, account: Account, *, ttl: timedelta) -> AccountSession:
        from .personas import AccountPersonaRow

        now = utc_now()
        token = secrets.token_urlsafe(32)
        expires_at = now + ttl
        with self.session_factory.begin() as database_session:
            active_persona_id = database_session.scalar(
                select(AccountPersonaRow.id)
                .where(AccountPersonaRow.account_id == str(account.id))
                .order_by(AccountPersonaRow.created_at.asc())
            )
            database_session.add(
                AuthSessionRow(
                    id=str(uuid4()),
                    account_id=str(account.id),
                    active_persona_id=active_persona_id,
                    token_hash=_token_hash(token),
                    created_at=now,
                    last_seen_at=now,
                    expires_at=expires_at,
                )
            )
        return AccountSession(token=token, account=account, expires_at=expires_at)

    def session_persona_id(self, token: str | None, *, account_id: UUID) -> UUID | None:
        if not token:
            return None
        from .personas import AccountPersonaRow

        now = utc_now()
        with self.session_factory() as database_session:
            row = database_session.scalar(
                select(AuthSessionRow).where(
                    AuthSessionRow.token_hash == _token_hash(token),
                    AuthSessionRow.account_id == str(account_id),
                    AuthSessionRow.expires_at > now,
                )
            )
            if row is None or row.active_persona_id is None:
                return None
            persona_account_id = database_session.scalar(
                select(AccountPersonaRow.account_id).where(
                    AccountPersonaRow.id == row.active_persona_id
                )
            )
            if persona_account_id != str(account_id):
                return None
            return UUID(row.active_persona_id)

    def set_session_persona(
        self,
        token: str | None,
        *,
        account_id: UUID,
        persona_id: UUID,
    ) -> None:
        if not token:
            raise AccountError("Sign in before switching personas.")
        from .personas import AccountPersonaRow

        now = utc_now()
        with self.session_factory.begin() as database_session:
            persona = database_session.get(AccountPersonaRow, str(persona_id))
            if persona is None or persona.account_id != str(account_id):
                raise AccountError("Persona not found.")
            row = database_session.scalar(
                select(AuthSessionRow).where(
                    AuthSessionRow.token_hash == _token_hash(token),
                    AuthSessionRow.account_id == str(account_id),
                    AuthSessionRow.expires_at > now,
                )
            )
            if row is None:
                raise AccountError("Your session expired. Sign in again.")
            row.active_persona_id = str(persona_id)
            row.last_seen_at = now

    def resolve_session(self, token: str | None) -> Account | None:
        if not token:
            return None
        now = utc_now()
        with self.session_factory.begin() as database_session:
            row = database_session.scalar(
                select(AuthSessionRow).where(
                    AuthSessionRow.token_hash == _token_hash(token),
                    AuthSessionRow.expires_at > now,
                )
            )
            if row is None:
                return None
            account = database_session.get(AccountRow, row.account_id)
            if account is None or account.email_verified_at is None:
                return None
            if now - ensure_utc(row.last_seen_at) >= timedelta(minutes=5):
                row.last_seen_at = now
            return self._to_account(account)

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self.session_factory.begin() as database_session:
            database_session.execute(
                delete(AuthSessionRow).where(AuthSessionRow.token_hash == _token_hash(token))
            )

    def delete_account(self, account_id: UUID) -> bool:
        with self.session_factory.begin() as database_session:
            row = database_session.scalar(
                select(AccountRow).where(AccountRow.id == str(account_id)).with_for_update()
            )
            if row is None:
                return False
            if row.role == AccountRole.ADMIN.value:
                admin_ids = database_session.scalars(
                    select(AccountRow.id)
                    .where(AccountRow.role == AccountRole.ADMIN.value)
                    .with_for_update()
                ).all()
                account_count = int(database_session.scalar(select(func.count(AccountRow.id))) or 0)
                if len(admin_ids) <= 1 and account_count > 1:
                    raise AccountError(
                        "Promote another admin before deleting the last admin account."
                    )
            database_session.delete(row)
            return True

    def export_json(self, account_id: UUID) -> str:
        """Return the complete private account graph without authentication secrets."""

        from .background import BackgroundTaskRow
        from .application_guidance import ApplicationGuidanceOverrideRow
        from .applications import ApplicationDraftRow
        from .cv import CvDocumentRow
        from .employer_reputation import EmployerReputationRatingRow
        from .explore_repository import ExploreSearchRow
        from .feedback import ProductFeedbackRow
        from .legal import LegalAcceptanceRow
        from .mobility import CommuteEstimateRow
        from .operations import ProviderOperationRow
        from .personas import AccountPersonaRow
        from .portal_sources import PersonaPortalSourceRow
        from .profile_repository import ConversationMessageRow
        from .provider_permissions import AccountProviderPreferenceRow
        from .job_overrides import JobEvidenceOverrideRow
        from .job_ratings import PersonaJobRatingRow
        from .job_posters import EmployerJobPostingRow, JobPosterAccessRow
        from .result_repository import (
            JobInteractionEventRow,
            JobInteractionRow,
            MatchResultRow,
            MatchRunRow,
        )

        def row_dict(row, *, exclude: set[str] | None = None) -> dict:
            excluded = exclude or set()
            payload = {}
            for column in row.__table__.columns:
                if column.name in excluded:
                    continue
                value = getattr(row, column.name)
                payload[column.name] = (
                    value.isoformat() if isinstance(value, (date, datetime)) else value
                )
            return payload

        with self.session_factory() as database_session:
            account = database_session.get(AccountRow, str(account_id))
            if account is None:
                raise KeyError(f"unknown account: {account_id}")
            workspaces = database_session.scalars(
                select(ProfileWorkspaceRow).where(ProfileWorkspaceRow.account_id == str(account_id))
            ).all()
            workspace_ids = [row.id for row in workspaces]
            runs = (
                database_session.scalars(
                    select(MatchRunRow).where(MatchRunRow.workspace_id.in_(workspace_ids))
                ).all()
                if workspace_ids
                else []
            )
            run_ids = [row.id for row in runs]

            def workspace_rows(model):
                if not workspace_ids:
                    return []
                return database_session.scalars(
                    select(model).where(model.workspace_id.in_(workspace_ids))
                ).all()

            tasks = workspace_rows(BackgroundTaskRow)
            personas = database_session.scalars(
                select(AccountPersonaRow).where(AccountPersonaRow.account_id == str(account_id))
            ).all()
            persona_ids = [row.id for row in personas]
            export = {
                "exported_at": utc_now().isoformat(),
                "account": row_dict(account, exclude={"password_hash"}),
                "legal_acceptances": [
                    row_dict(row)
                    for row in database_session.scalars(
                        select(LegalAcceptanceRow).where(
                            LegalAcceptanceRow.account_id == str(account_id)
                        )
                    ).all()
                ],
                "personas": [row_dict(row) for row in personas],
                "provider_preferences": [
                    row_dict(row)
                    for row in database_session.scalars(
                        select(AccountProviderPreferenceRow).where(
                            AccountProviderPreferenceRow.account_id == str(account_id)
                        )
                    ).all()
                ],
                "provider_operations": [
                    row_dict(row)
                    for row in database_session.scalars(
                        select(ProviderOperationRow).where(
                            ProviderOperationRow.account_id == str(account_id)
                        )
                    ).all()
                ],
                "product_feedback": [
                    row_dict(row)
                    for row in database_session.scalars(
                        select(ProductFeedbackRow).where(
                            ProductFeedbackRow.account_id == str(account_id)
                        )
                    ).all()
                ],
                "job_poster_access": (
                    row_dict(poster_access)
                    if (
                        poster_access := database_session.get(
                            JobPosterAccessRow,
                            str(account_id),
                        )
                    )
                    else None
                ),
                "employer_job_postings": [
                    row_dict(row)
                    for row in database_session.scalars(
                        select(EmployerJobPostingRow).where(
                            EmployerJobPostingRow.owner_account_id == str(account_id)
                        )
                    ).all()
                ],
                "persona_portal_sources": [
                    row_dict(row)
                    for row in (
                        database_session.scalars(
                            select(PersonaPortalSourceRow).where(
                                PersonaPortalSourceRow.persona_id.in_(persona_ids)
                            )
                        ).all()
                        if persona_ids
                        else []
                    )
                ],
                "employer_reputation_ratings": [
                    row_dict(row)
                    for row in (
                        database_session.scalars(
                            select(EmployerReputationRatingRow).where(
                                EmployerReputationRatingRow.persona_id.in_(persona_ids)
                            )
                        ).all()
                        if persona_ids
                        else []
                    )
                ],
                "persona_job_ratings": [
                    row_dict(row)
                    for row in (
                        database_session.scalars(
                            select(PersonaJobRatingRow).where(
                                PersonaJobRatingRow.persona_id.in_(persona_ids)
                            )
                        ).all()
                        if persona_ids
                        else []
                    )
                ],
                "workspaces": [row_dict(row) for row in workspaces],
                "conversation_messages": [
                    row_dict(row) for row in workspace_rows(ConversationMessageRow)
                ],
                "cv_documents": [row_dict(row) for row in workspace_rows(CvDocumentRow)],
                "application_drafts": [
                    row_dict(row) for row in workspace_rows(ApplicationDraftRow)
                ],
                "application_guidance_overrides": [
                    row_dict(row) for row in workspace_rows(ApplicationGuidanceOverrideRow)
                ],
                "job_evidence_overrides": [
                    row_dict(row) for row in workspace_rows(JobEvidenceOverrideRow)
                ],
                "saved_job_access": [row_dict(row) for row in workspace_rows(ResultAccessGrantRow)],
                "match_runs": [row_dict(row) for row in runs],
                "match_results": [
                    row_dict(row)
                    for row in (
                        database_session.scalars(
                            select(MatchResultRow).where(MatchResultRow.match_run_id.in_(run_ids))
                        ).all()
                        if run_ids
                        else []
                    )
                ],
                "job_interactions": [row_dict(row) for row in workspace_rows(JobInteractionRow)],
                "job_interaction_events": [
                    row_dict(row) for row in workspace_rows(JobInteractionEventRow)
                ],
                "commute_estimates": [row_dict(row) for row in workspace_rows(CommuteEstimateRow)],
                "background_tasks": [row_dict(row) for row in tasks],
                "explore_searches": [
                    row_dict(row)
                    for row in (
                        database_session.scalars(
                            select(ExploreSearchRow).where(
                                ExploreSearchRow.workspace_id.in_(workspace_ids)
                            )
                        ).all()
                        if workspace_ids
                        else []
                    )
                ],
                "shared_public_job_corpus_note": (
                    "Public job advertisements are shared source data and are not part of "
                    "the private account graph. Saved-job access is exported above."
                ),
            }
            return json.dumps(export, ensure_ascii=False, indent=2)

    def export_portable_json(self, account_id: UUID) -> str:
        """Return a small user-facing account, persona, and current-Compass export.

        The complete private graph remains available to the operational export
        above.  This projection deliberately omits provider operations, task and
        match histories, raw conversations, internal ids, and revision/audit
        details which are useful for support but not for a portable profile.
        """

        from .legal import LegalAcceptanceRow
        from .personas import AccountPersonaRow
        from .session import ProfileSession

        def timestamp(value: date | datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        def compass_payload(workspace: ProfileWorkspaceRow | None) -> dict | None:
            if workspace is None:
                return None
            session = ProfileSession.model_validate_json(workspace.session_json)
            profile = session.profile
            return {
                "protocol_version": profile.protocol_version,
                "updated_at": timestamp(profile.updated_at),
                "setup": [
                    {
                        "section": progress.section.value,
                        "status": progress.status.value,
                        "summary": progress.summary,
                    }
                    for progress in session.sections
                ],
                "location": (
                    profile.location.model_dump(mode="json") if profile.location else None
                ),
                "work_model": profile.work_model.model_dump(mode="json"),
                "compensation": profile.compensation.model_dump(mode="json"),
                "statements": [
                    {
                        "section": fact.source.section.value,
                        "key": fact.key,
                        "value": fact.value,
                        "importance": fact.level.value,
                        "note": fact.user_note,
                    }
                    for fact in profile.confirmed_facts
                ],
                "open_questions": list(profile.unresolved_questions),
            }

        with self.session_factory() as database_session:
            account = database_session.get(AccountRow, str(account_id))
            if account is None:
                raise KeyError(f"unknown account: {account_id}")
            personas = database_session.scalars(
                select(AccountPersonaRow)
                .where(AccountPersonaRow.account_id == str(account_id))
                .order_by(AccountPersonaRow.created_at.asc())
            ).all()
            workspaces = database_session.scalars(
                select(ProfileWorkspaceRow)
                .where(ProfileWorkspaceRow.account_id == str(account_id))
                .order_by(
                    ProfileWorkspaceRow.active.desc(),
                    ProfileWorkspaceRow.updated_at.desc(),
                )
            ).all()
            current_workspace_by_persona: dict[str, ProfileWorkspaceRow] = {}
            for workspace in workspaces:
                if workspace.persona_id:
                    current_workspace_by_persona.setdefault(workspace.persona_id, workspace)
            acceptances = database_session.scalars(
                select(LegalAcceptanceRow)
                .where(LegalAcceptanceRow.account_id == str(account_id))
                .order_by(LegalAcceptanceRow.accepted_at.asc())
            ).all()
            payload = {
                "format": "worklifebalance-portable-profile-v1",
                "exported_at": utc_now().isoformat(),
                "account": {
                    "email": account.email,
                    "display_name": account.display_name,
                    "email_verified_at": timestamp(account.email_verified_at),
                    "created_at": timestamp(account.created_at),
                    "updated_at": timestamp(account.updated_at),
                    "legal_documents": [
                        {
                            "kind": row.document_kind,
                            "version": row.document_version,
                            "accepted_at": timestamp(row.accepted_at),
                        }
                        for row in acceptances
                    ],
                },
                "personas": [
                    {
                        "name": persona.name,
                        "also_update_compass_skills": persona.also_update_compass_skills,
                        "created_at": timestamp(persona.created_at),
                        "updated_at": timestamp(persona.updated_at),
                        "compass": compass_payload(current_workspace_by_persona.get(persona.id)),
                    }
                    for persona in personas
                ],
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
