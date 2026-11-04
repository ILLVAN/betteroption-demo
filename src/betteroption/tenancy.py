"""Request-safe tenant context for repositories and background workflows."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID


LOCAL_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_current_tenant_id: ContextVar[UUID] = ContextVar(
    "betteroption_tenant_id",
    default=LOCAL_TENANT_ID,
)


def current_tenant_id() -> UUID:
    """Return the tenant selected for the current request or worker task."""

    return _current_tenant_id.get()


@contextmanager
def tenant_scope(tenant_id: UUID) -> Iterator[None]:
    """Temporarily select a tenant and restore the previous context afterwards."""

    token = _current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(token)
