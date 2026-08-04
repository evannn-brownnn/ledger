"""Declarative base and shared column conventions.

The naming convention below is not cosmetic. Alembic's autogenerate needs
deterministic constraint names to emit correct migrations — without it, you
get migrations that try to drop constraints by names Postgres invented, and
they fail in confusing ways on other machines.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Never use datetime.utcnow() — it returns a naive datetime that silently
    compares wrong against aware ones. This is a genuinely common production
    bug.
    """
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class UUIDPrimaryKey:
    """Mixin: string UUID primary key.

    UUIDs over sequential integers because ledger IDs may be exposed to
    clients and issued by more than one writer. If you later want ordering,
    consider UUIDv7 rather than reintroducing a sequence.
    """

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class CreatedAt:
    """Mixin: immutable creation timestamp.

    Note there is deliberately no `updated_at` anywhere in this schema.
    Journal rows are never updated, so an update timestamp would be a lie.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
