"""ORM models for the ledger domain.

>>> THIS IS YOURS TO WRITE. See app/models/__init__.py for the full spec. <<<
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import NUMERIC, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey, utcnow


class Account(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "normal_balance IN ('debit', 'credit')",
            name="normal_balance_valid",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    normal_balance: Mapped[str] = mapped_column(String(6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class Transaction(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "transactions"

    memo: Mapped[str] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reverses_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True, unique=True
    )


class TransactionLine(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "transaction_lines"
    __table_args__ = (
        CheckConstraint("direction IN ('debit', 'credit')", name="direction_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(None, "account_id", "created_at"),
    )

    # Overrides CreatedAt's plain column: this table's PK is (id, created_at),
    # not just id, so monthly RANGE partitioning is possible later without a
    # rewrite. See docs/adr/0003-balance-snapshots-and-partitioning.md.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=utcnow, nullable=False
    )

    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=False, index=True
    )
    # No standalone index here: the (account_id, created_at) composite above
    # already serves account_id-only lookups via the leftmost-prefix rule.
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(NUMERIC(20, 4), nullable=False)


class IdempotencyKey(CreatedAt, Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=False
    )


class AuditEvent(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "audit_events"

    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    # No ForeignKey here on purpose: entity_type/entity_id together form a
    # polymorphic pointer across every table in this schema (an account, a
    # transaction, whatever), so no single column could ever be a real FK
    # target. Validated by application code, not the database.
    entity_type: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
