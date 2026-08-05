"""ORM models for the ledger domain.

>>> THIS IS YOURS TO WRITE. See app/models/__init__.py for the full spec. <<<
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


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
