"""Ledger HTTP routes.

The routing, validation, status codes, dependency wiring and OpenAPI
documentation are complete. The bodies call into `app.domain.ledger`, which
is where your work goes — so these will 501 until you implement the domain
functions, and start working the moment you do.

Note the transaction-boundary choice in each handler:

  * Reads use the plain request session (READ COMMITTED). Fine — a slightly
    stale balance read is acceptable and the alternative costs throughput.

  * Writes go through `serializable_transaction`, which runs at SERIALIZABLE
    and retries on 40001. This is the safe default for anything that reads
    state and then writes based on it. See docs/adr/0002.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query, status

from app.api.deps import FingerprintDep, IdempotencyKeyDep, SessionDep
from app.api.schemas import (
    AccountIn,
    AccountOut,
    BalanceOut,
    ReversalIn,
    StatementOut,
    TransactionIn,
    TransactionOut,
)
from app.db import serializable_transaction
from app.domain import ledger as domain
from app.observability import POSTINGS, get_logger

router = APIRouter(tags=["ledger"])
log = get_logger("api.ledger")


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
def create_account(body: AccountIn, session: SessionDep) -> AccountOut:
    """Add an account to the chart of accounts.

    `normal_balance` determines the sign convention for this account's
    reported balance and cannot be changed afterwards.
    """
    raise NotImplementedError("implement Account creation")


@router.get("/accounts", response_model=list[AccountOut], summary="List accounts")
def list_accounts(session: SessionDep) -> list[AccountOut]:
    raise NotImplementedError("implement account listing")


@router.post(
    "/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Post a journal entry",
    responses={
        409: {"description": "Conflicted with a concurrent transaction"},
        422: {"description": "Unbalanced, invalid, or idempotency-key conflict"},
        503: {"description": "Retry exhausted; safe to retry with the same key"},
    },
)
def post_transaction(
    body: TransactionIn,
    session: SessionDep,
    idem_key: IdempotencyKeyDep,
    fingerprint: FingerprintDep,
) -> TransactionOut:
    """Append a balanced, immutable journal entry.

    Send an `Idempotency-Key` header for any request you might retry — which,
    over a network, is all of them. Retrying with the same key and the same
    body returns the original transaction rather than posting twice.

    Sum of debit legs must equal sum of credit legs exactly.
    """
    legs = [
        domain.Leg(
            account_id=leg.account_id, direction=leg.direction, amount=leg.amount
        )
        for leg in body.legs
    ]

    def _work(s):  # type: ignore[no-untyped-def]
        return domain.post_transaction(
            s,
            legs=legs,
            currency=body.currency,
            memo=body.memo,
            idempotency_key=idem_key,
            request_hash=fingerprint,
        )

    txn = serializable_transaction(_work)
    POSTINGS.labels("committed").inc()
    log.info("transaction_posted", transaction_id=getattr(txn, "id", None))
    return TransactionOut.model_validate(txn)


@router.post(
    "/transactions/{transaction_id}/reversal",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reverse a journal entry",
    responses={409: {"description": "Already reversed, or is itself a reversal"}},
)
def reverse_transaction(
    transaction_id: str,
    body: ReversalIn,
    session: SessionDep,
    idem_key: IdempotencyKeyDep,
) -> TransactionOut:
    """Correct a posting by appending its mirror image.

    The original is never modified. Both entries remain in the journal, which
    is what makes the correction auditable.
    """

    def _work(s):  # type: ignore[no-untyped-def]
        return domain.reverse_transaction(
            s,
            transaction_id=transaction_id,
            memo=body.memo,
            idempotency_key=idem_key,
        )

    txn = serializable_transaction(_work)
    return TransactionOut.model_validate(txn)


@router.get(
    "/accounts/{account_id}/balance",
    response_model=BalanceOut,
    summary="Get an account balance",
)
def get_balance(
    account_id: str,
    session: SessionDep,
    as_of: datetime | None = Query(
        None, description="Point-in-time balance. Defaults to now."
    ),
) -> BalanceOut:
    """Balance derived from the journal — there is no stored balance column.

    `as_of` reconstructs the balance at any past instant, which is possible
    precisely because the journal is append-only.
    """
    raise NotImplementedError("implement balance()")


@router.get(
    "/accounts/{account_id}/statement",
    response_model=StatementOut,
    summary="Account statement",
)
def get_statement(
    account_id: str,
    session: SessionDep,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = Query(None, description="Opaque keyset cursor"),
) -> StatementOut:
    """Paginated history with a running balance. Keyset paginated, not OFFSET."""
    raise NotImplementedError("implement account_statement()")


@router.get(
    "/reconciliation/trial-balance",
    summary="Verify the book balances",
    responses={500: {"description": "The book does not balance — stop everything"}},
)
def trial_balance(session: SessionDep) -> dict[str, object]:
    """Global invariant: total debits minus total credits must be exactly zero.

    Expose this, alert on it, and run it on a schedule. If it is ever
    non-zero, financial data has been corrupted and nothing else matters
    until you know why.
    """
    delta = domain.trial_balance(session)
    return {
        "balanced": delta == 0,
        "delta": str(delta),
        "checked_at": datetime.now(UTC).isoformat(),
    }
