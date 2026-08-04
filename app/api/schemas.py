"""Request and response contracts.

Pydantic models are your boundary. Anything that reaches domain code has
already been shape-checked, type-coerced and range-validated here — which
is why domain functions can assume clean input and focus on ledger rules.

Note `condecimal(...)`: amounts arrive as JSON numbers or strings and become
Decimal, never float. `max_digits`/`decimal_places` mirror the NUMERIC(20,4)
column so a value that cannot be stored is rejected at the edge rather than
blowing up on INSERT.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Money = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)]
Currency = Annotated[
    str,
    StringConstraints(min_length=3, max_length=3, to_upper=True, pattern=r"^[A-Z]{3}$"),
]
Direction = Literal["debit", "credit"]


class LegIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # typos become errors, not silence

    account_id: str
    direction: Direction
    amount: Money


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legs: list[LegIn] = Field(min_length=2, max_length=64)
    currency: Currency = "USD"
    memo: str = Field(default="", max_length=256)

    @field_validator("legs")
    @classmethod
    def _must_balance(cls, legs: list[LegIn]) -> list[LegIn]:
        """Cheap pre-check so obviously-wrong requests never touch the DB.

        The authoritative check still lives in the domain layer — this is a
        fast fail, not the guarantee.
        """
        debits = sum(
            (leg.amount for leg in legs if leg.direction == "debit"), Decimal(0)
        )
        credits = sum(
            (leg.amount for leg in legs if leg.direction == "credit"), Decimal(0)
        )
        if debits != credits:
            raise ValueError(f"unbalanced: debits {debits} != credits {credits}")
        if debits == 0:
            raise ValueError("transaction total must be greater than zero")
        return legs


class LegOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    direction: Direction
    amount: Decimal


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    memo: str
    currency: str
    reverses_id: str | None
    created_at: datetime
    lines: list[LegOut]


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    normal_balance: Direction
    currency: Currency = "USD"


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    normal_balance: Direction
    currency: str
    created_at: datetime


class BalanceOut(BaseModel):
    account_id: str
    currency: str
    balance: Decimal
    as_of: datetime


class ReversalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memo: str = Field(default="", max_length=256)


class StatementLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    direction: Direction
    amount: Decimal
    running_balance: Decimal
    memo: str
    created_at: datetime


class StatementOut(BaseModel):
    account_id: str
    lines: list[StatementLine]
    next_cursor: str | None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool]
