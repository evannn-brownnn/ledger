"""Executable specification for the ledger domain.

These tests are the requirements document. They currently fail because
`app/domain/ledger.py` raises NotImplementedError. Making them pass, without
weakening them, is the assignment.

Read them in order — they are arranged from "obviously true" to "the reason
this job is hard".

If you find yourself editing a test to make it pass, stop and be sure the
test is genuinely wrong. Usually it isn't.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

import pytest

from app.domain.errors import (
    AlreadyReversed,
    CannotReverseReversal,
    CurrencyMismatch,
    IdempotencyKeyConflict,
    InvalidPosting,
    UnbalancedTransaction,
)
from app.domain.ledger import (
    Leg,
    balance,
    post_transaction,
    reverse_transaction,
    trial_balance,
)

D = Decimal
pytestmark = pytest.mark.integration


# --- the happy path ----------------------------------------------------------


def test_balanced_posting_moves_both_sides(session, accounts):
    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("100.00")),
            Leg(accounts["user_wallet"].id, "credit", D("100.00")),
        ],
        memo="deposit",
    )
    assert balance(session, accounts["platform_cash"].id) == D("100.00")
    assert balance(session, accounts["user_wallet"].id) == D("100.00")
    assert trial_balance(session) == D("0")


def test_multi_leg_split_with_fee(session, accounts):
    """100.00 in, 97.50 to the user, 2.50 kept as fee. Three legs, still balanced."""
    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("100.00")),
            Leg(accounts["user_wallet"].id, "credit", D("97.50")),
            Leg(accounts["fee_revenue"].id, "credit", D("2.50")),
        ],
    )
    assert balance(session, accounts["user_wallet"].id) == D("97.50")
    assert balance(session, accounts["fee_revenue"].id) == D("2.50")
    assert trial_balance(session) == D("0")


def test_normal_balance_sign_convention(session, accounts):
    """A credit-normal account debited goes negative; a debit-normal one positive."""
    post_transaction(
        session,
        legs=[
            Leg(accounts["user_wallet"].id, "debit", D("10.00")),
            Leg(accounts["platform_cash"].id, "credit", D("10.00")),
        ],
    )
    assert balance(session, accounts["user_wallet"].id) == D("-10.00")
    assert balance(session, accounts["platform_cash"].id) == D("-10.00")


# --- rejections --------------------------------------------------------------


def test_unbalanced_is_rejected(session, accounts):
    with pytest.raises(UnbalancedTransaction):
        post_transaction(
            session,
            legs=[
                Leg(accounts["platform_cash"].id, "debit", D("100.00")),
                Leg(accounts["user_wallet"].id, "credit", D("99.99")),
            ],
        )
    assert trial_balance(session) == D("0")  # nothing was written


def test_single_leg_is_rejected(session, accounts):
    with pytest.raises(InvalidPosting):
        post_transaction(
            session, legs=[Leg(accounts["platform_cash"].id, "debit", D("10.00"))]
        )


@pytest.mark.parametrize("amount", [D("0"), D("-1.00"), D("-0.0001")])
def test_non_positive_amounts_rejected(session, accounts, amount):
    with pytest.raises(InvalidPosting):
        post_transaction(
            session,
            legs=[
                Leg(accounts["platform_cash"].id, "debit", amount),
                Leg(accounts["user_wallet"].id, "credit", amount),
            ],
        )


def test_mixed_currency_rejected(session, accounts, eur_account):
    """Cross-currency movement is two transactions plus an FX position,
    never one transaction. Rejecting it here keeps the book honest."""
    with pytest.raises(CurrencyMismatch):
        post_transaction(
            session,
            legs=[
                Leg(accounts["platform_cash"].id, "debit", D("100.00")),
                Leg(eur_account.id, "credit", D("100.00")),
            ],
            currency="USD",
        )


# --- money precision ---------------------------------------------------------


def test_no_float_drift(session, accounts):
    """Ten postings of 0.01 must total exactly 0.10.

    If this fails you have a float somewhere. Find it.
    """
    for _ in range(10):
        post_transaction(
            session,
            legs=[
                Leg(accounts["platform_cash"].id, "debit", D("0.01")),
                Leg(accounts["user_wallet"].id, "credit", D("0.01")),
            ],
        )
    assert balance(session, accounts["user_wallet"].id) == D("0.10")


def test_scale_is_normalised(session, accounts):
    """10.0000 and 10.00 are the same amount and must compare equal."""
    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("10.0000")),
            Leg(accounts["user_wallet"].id, "credit", D("10.00")),
        ],
    )
    assert balance(session, accounts["user_wallet"].id) == D("10")


def test_sub_cent_fee_arithmetic(session, accounts):
    """Four decimal places must survive. 0.0025 is a real fee, not a rounding error."""
    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("1.0000")),
            Leg(accounts["user_wallet"].id, "credit", D("0.9975")),
            Leg(accounts["fee_revenue"].id, "credit", D("0.0025")),
        ],
    )
    assert balance(session, accounts["fee_revenue"].id) == D("0.0025")
    assert trial_balance(session) == D("0")


# --- idempotency -------------------------------------------------------------


def test_same_key_same_body_returns_original(session, accounts):
    legs = [
        Leg(accounts["platform_cash"].id, "debit", D("50.00")),
        Leg(accounts["user_wallet"].id, "credit", D("50.00")),
    ]
    first = post_transaction(
        session, legs=legs, idempotency_key="k-1", request_hash="h-1"
    )
    second = post_transaction(
        session, legs=legs, idempotency_key="k-1", request_hash="h-1"
    )
    assert first.id == second.id
    assert balance(session, accounts["user_wallet"].id) == D("50.00")


def test_same_key_different_body_is_a_conflict(session, accounts):
    """Reusing a key with a different payload is a client bug.

    Silently replaying the original would hide a mistake with financial
    consequences. Fail loudly.
    """
    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("50.00")),
            Leg(accounts["user_wallet"].id, "credit", D("50.00")),
        ],
        idempotency_key="k-2",
        request_hash="h-a",
    )
    with pytest.raises(IdempotencyKeyConflict):
        post_transaction(
            session,
            legs=[
                Leg(accounts["platform_cash"].id, "debit", D("999.00")),
                Leg(accounts["user_wallet"].id, "credit", D("999.00")),
            ],
            idempotency_key="k-2",
            request_hash="h-b",
        )


def test_no_key_means_no_dedupe(session, accounts):
    """Two identical postings without a key are two legitimate transactions.

    A customer may genuinely buy the same coffee twice.
    """
    legs = [
        Leg(accounts["platform_cash"].id, "debit", D("5.00")),
        Leg(accounts["user_wallet"].id, "credit", D("5.00")),
    ]
    a = post_transaction(session, legs=legs)
    b = post_transaction(session, legs=legs)
    assert a.id != b.id
    assert balance(session, accounts["user_wallet"].id) == D("10.00")


# --- reversals ---------------------------------------------------------------


def test_reversal_zeroes_the_effect_and_keeps_history(session, accounts):
    txn = post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("75.00")),
            Leg(accounts["user_wallet"].id, "credit", D("75.00")),
        ],
        memo="mistake",
    )
    rev = reverse_transaction(session, transaction_id=txn.id)

    assert balance(session, accounts["user_wallet"].id) == D("0")
    assert rev.reverses_id == txn.id
    # The original still exists, unmodified. That is the whole point.
    assert len(txn.lines) == 2
    assert trial_balance(session) == D("0")


def test_cannot_reverse_twice(session, accounts):
    txn = post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("20.00")),
            Leg(accounts["user_wallet"].id, "credit", D("20.00")),
        ],
    )
    reverse_transaction(session, transaction_id=txn.id)
    with pytest.raises(AlreadyReversed):
        reverse_transaction(session, transaction_id=txn.id)


def test_cannot_reverse_a_reversal(session, accounts):
    txn = post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("20.00")),
            Leg(accounts["user_wallet"].id, "credit", D("20.00")),
        ],
    )
    rev = reverse_transaction(session, transaction_id=txn.id)
    with pytest.raises(CannotReverseReversal):
        reverse_transaction(session, transaction_id=rev.id)


# --- point in time -----------------------------------------------------------


def test_historical_balance(session, accounts):
    """`as_of` must reconstruct the balance at a past instant.

    This works only because the journal is append-only. If you ever add a
    mutable balance column, this test becomes unimplementable — which is a
    good reason to keep it.
    """
    import time
    from datetime import datetime

    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("10.00")),
            Leg(accounts["user_wallet"].id, "credit", D("10.00")),
        ],
    )
    session.flush()
    time.sleep(0.01)
    checkpoint = datetime.now(UTC)
    time.sleep(0.01)

    post_transaction(
        session,
        legs=[
            Leg(accounts["platform_cash"].id, "debit", D("5.00")),
            Leg(accounts["user_wallet"].id, "credit", D("5.00")),
        ],
    )
    session.flush()

    assert balance(session, accounts["user_wallet"].id) == D("15.00")
    assert balance(session, accounts["user_wallet"].id, as_of=checkpoint) == D("10.00")


# --- the invariant, under abuse ----------------------------------------------


def test_fuzz_book_always_balances(session, accounts):
    """Two thousand random postings. The trial balance must never move."""
    import random

    rng = random.Random(1337)
    names = list(accounts)
    for _ in range(2000):
        src, dst = rng.sample(names, 2)
        amount = D(rng.randint(1, 1_000_000)) / D("10000")
        post_transaction(
            session,
            legs=[
                Leg(accounts[src].id, "debit", amount),
                Leg(accounts[dst].id, "credit", amount),
            ],
        )
    assert trial_balance(session) == D("0")


def test_failed_postings_leave_no_trace(session, accounts):
    """A rejected posting must not write partial rows.

    Interleave valid and invalid postings; only the valid ones may land.
    """
    good = [
        Leg(accounts["platform_cash"].id, "debit", D("10.00")),
        Leg(accounts["user_wallet"].id, "credit", D("10.00")),
    ]
    bad = [
        Leg(accounts["platform_cash"].id, "debit", D("10.00")),
        Leg(accounts["user_wallet"].id, "credit", D("9.00")),
    ]
    for _ in range(5):
        post_transaction(session, legs=good)
        with pytest.raises(UnbalancedTransaction):
            post_transaction(session, legs=bad)

    assert balance(session, accounts["user_wallet"].id) == D("50.00")
    assert trial_balance(session) == D("0")
