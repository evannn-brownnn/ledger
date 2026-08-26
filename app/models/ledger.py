from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    NUMERIC,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey, utcnow


class Account(UUIDPrimaryKey, CreatedAt, Base):
    """A ledger account. Never holds a balance — that is derived from
    TransactionLine rows. `normal_balance` fixes the sign convention: a
    debit-normal account's balance is debits minus credits, a credit-normal
    account's is credits minus debits.
    """

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
    """One journal entry: an immutable, balanced group of TransactionLine
    rows. Never updated or deleted — a correction is a new Transaction with
    `reverses_id` pointing back at this one. The UNIQUE constraint on
    `reverses_id` guarantees at most one reversal per original.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        # Column order here is deliberate, not decorative. Left to declaration
        # order this would come out (created_at, id), the way transaction_lines
        # did — and then a lookup by id alone could not use the PK index at all,
        # because a B-tree only helps when the filter includes the leftmost
        # column. Looking a transaction up by id is the single most common
        # access path in the system (reverse_transaction, GET by id), so id
        # leads. An explicit PrimaryKeyConstraint is the only way to pin the
        # order independently of where the columns happen to be declared.
        PrimaryKeyConstraint("id", "created_at"),
    )

    # Overrides CreatedAt's plain column to join the PK: Postgres requires the
    # partition key to be part of the primary key, and this table is destined
    # for monthly RANGE partitioning on created_at. Decided up front because
    # retrofitting it onto a populated table means a full copy — see
    # docs/adr/0003-balance-snapshots-and-partitioning.md.
    #
    # index=True is kept (unlike transaction_lines, which drops it): created_at
    # is the *trailing* PK column here, so the PK index does nothing for
    # created_at range scans and a standalone index still earns its place.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=utcnow,
        nullable=False,
        index=True,
    )

    memo: Mapped[str] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # No ForeignKey. A bare-id FK cannot reference the (id, created_at)
    # key, and we chose not to carry a composite one — ADR 0003 "Decision:
    # foreign keys". Composite FKs to a partitioned table DO work on PG 12+;
    # this is a simplicity trade, not a platform limit. Don't "fix" it back.
    #
    # The UNIQUE survives, so reverse-once stays a database guarantee
    # (ADR 0002). Only "the target exists" moves to domain code.
    reverses_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, unique=True
    )


class TransactionLine(UUIDPrimaryKey, CreatedAt, Base):
    """One side (debit or credit) of a Transaction, against a single
    Account. A Transaction's lines must sum to zero across debits and
    credits — that invariant is enforced by domain code, not a constraint
    here, since it spans multiple rows.
    """

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

    # Conceptual link, not a constraint — see Transaction.reverses_id.
    # An orphaned line is now possible at the database level and only
    # post_transaction() prevents it. This is the one place the trade
    # actually costs something: an orphaned line is a hole in the journal,
    # unlike an orphaned idempotency key. Reconciliation (milestone 5)
    # should look for them.
    transaction_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    # No standalone index here: the (account_id, created_at) composite above
    # already serves account_id-only lookups via the leftmost-prefix rule.
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(NUMERIC(20, 4), nullable=False)


class IdempotencyKey(CreatedAt, Base):
    """Records that a client-supplied key has already produced a
    Transaction. `key` is the primary key, so a concurrent duplicate insert
    fails on the UNIQUE constraint rather than a check-then-act race.
    `request_hash` lets a replayed key be told apart from a reused one.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Conceptual link. ADR 0003 accepts orphans here as harmless: a race
    # where the key was inserted and the posting then failed.
    transaction_id: Mapped[str] = mapped_column(String(36), nullable=False)


class AuditEvent(UUIDPrimaryKey, CreatedAt, Base):
    """A record of who did what to which entity, independent of the
    financial journal. `entity_type`/`entity_id` point at a row in any
    other table, which is why there is no ForeignKey here.
    """

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
