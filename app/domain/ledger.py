"""Ledger domain logic.

>>> THIS IS YOURS TO WRITE. <<<

Every function below is specified in its docstring and raises
NotImplementedError. `tests/unit/test_ledger_domain.py` encodes these
specifications as executable tests. Make them pass.

Ground rules for everything in this module:

  * It never commits. The caller owns the transaction boundary.
  * It never touches HTTP, logging config, or settings side effects.
  * It uses Decimal for money. Never float. Not once.
  * It raises the exceptions in `app.domain.errors`, never bare ValueError.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

Direction = Literal["debit", "credit"]


@dataclass(frozen=True)
class Leg:
    """One side of a posting. Frozen because a leg is a value, not a record."""

    account_id: str
    direction: Direction
    amount: Decimal


def post_transaction(
    session: Session,
    *,
    legs: list[Leg],
    currency: str = "USD",
    memo: str = "",
    idempotency_key: str | None = None,
    request_hash: str | None = None,
    reverses_id: str | None = None,
) -> object:  # -> Transaction, once you have defined the model
    """Append one balanced, immutable journal entry.

    MUST enforce, in this order:

      1. len(legs) >= 2                        -> InvalidPosting
      2. every amount > 0                      -> InvalidPosting
      3. every direction in {debit, credit}    -> InvalidPosting
      4. every account exists                  -> AccountNotFound
      5. every account.currency == currency,
         and currency is supported             -> CurrencyMismatch
      6. sum(debits) == sum(credits) exactly   -> UnbalancedTransaction

    Compare sums as Decimal. `Decimal("0.1") * 3 != Decimal("0.3")` is fine
    to reason about; float 0.1 * 3 is not. Quantize to settings.amount_scale
    before comparing so 10.00 and 10.0000 are equal.

    IDEMPOTENCY

    If `idempotency_key` is given:
      * If the key exists and request_hash matches -> return the ORIGINAL
        transaction. Do not create anything.
      * If the key exists and request_hash differs -> IdempotencyKeyConflict.
      * If it does not exist -> insert it in the SAME transaction as the
        journal rows.

    Do NOT implement this as "SELECT, then INSERT if missing". Two concurrent
    requests both pass the SELECT and both insert. Rely on the UNIQUE
    constraint: attempt the insert, catch IntegrityError, then re-read to
    find the winner. The database is the arbiter, not your code.

    Be careful with session state after catching IntegrityError — a failed
    flush poisons the session. Use a SAVEPOINT (`session.begin_nested()`)
    so you can recover without discarding the outer transaction.

    Returns the created (or previously created) Transaction.
    """
    raise NotImplementedError


def reverse_transaction(
    session: Session,
    *,
    transaction_id: str,
    memo: str = "",
    idempotency_key: str | None = None,
) -> object:
    """Correct a posting by appending its mirror image.

    Nothing is ever updated or deleted. The correction is itself a fact in
    the journal, which is what makes the book auditable.

    MUST enforce:
      * the original exists                       -> TransactionNotFound
      * the original is not itself a reversal     -> CannotReverseReversal
      * the original has not been reversed        -> AlreadyReversed

    The third check must survive concurrency. Two simultaneous reversal
    requests must produce exactly one reversal. Do this with the UNIQUE
    constraint on transactions.reverses_id, not with a SELECT COUNT.

    The reversal has the same legs with directions flipped, the same
    amounts, and reverses_id pointing at the original.
    """
    raise NotImplementedError


def balance(
    session: Session,
    account_id: str,
    *,
    as_of: datetime | None = None,
) -> Decimal:
    """Current (or historical) balance, derived from the journal.

    Signed by the account's normal balance: for a debit-normal account,
    debits - credits; for credit-normal, credits - debits.

    `as_of` gives you point-in-time reporting for free, which is a genuinely
    strong thing to be able to demo. It also proves the journal really is
    the source of truth.

    MUST NOT read a stored balance column. There isn't one, and there must
    never be one. See docs/adr/0001.

    Performance note: this is a full scan of the account's lines. That is
    correct and fine until it isn't — milestone 5 adds snapshots. Do not
    optimise it before you have measured it.
    """
    raise NotImplementedError


def trial_balance(session: Session, *, as_of: datetime | None = None) -> Decimal:
    """Global invariant check: total debits minus total credits.

    MUST be exactly zero at all times, across the entire book. If it is
    ever non-zero you have a bug that has corrupted financial data, and
    everything else should stop until it is found.

    Run this at the end of every test and as a periodic reconciliation job.
    It is the cheapest, highest-value assertion in the system.
    """
    raise NotImplementedError


def account_statement(
    session: Session,
    account_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[object], str | None]:
    """Paginated line-by-line history with a running balance.

    Use keyset pagination — WHERE (created_at, id) < (:ts, :id) ORDER BY
    created_at DESC, id DESC — not OFFSET. OFFSET degrades linearly and,
    worse, skips or duplicates rows when new entries arrive mid-pagination.
    On an append-only table that happens constantly.

    Returns (lines, next_cursor). next_cursor is None on the last page.
    """
    raise NotImplementedError
