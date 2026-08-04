"""Concurrency tests — the ones that actually matter.

Everything in the single-threaded suite can pass while the service is still
badly broken under load. These tests use real threads and real connections,
because the bugs they hunt only exist when two transactions overlap.

Expect these to be the hardest tests to make pass. That is the point. If you
only take one thing from this project into a fintech interview, make it the
ability to explain why these tests exist and how you satisfied them.

Run with:  make test-integration
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select

D = Decimal
pytestmark = [pytest.mark.integration, pytest.mark.concurrency]


@pytest.fixture()
def real_sessions(engine):
    """Independent sessions on separate connections.

    The rolled-back `session` fixture cannot be used here: it shares one
    connection, so there is no real concurrency to test. These sessions
    commit for real, and the fixture cleans up afterwards.
    """
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    made: list = []

    def _make():
        s = factory()
        made.append(s)
        return s

    yield _make

    for s in made:
        s.rollback()
        s.close()


def test_concurrent_same_idempotency_key_posts_once(
    engine, real_sessions, seeded_accounts
):
    """N threads, one key, one transaction.

    This is the test that catches check-then-insert. If you implemented
    idempotency as SELECT-then-INSERT, every thread passes the SELECT and
    you get N duplicate postings — real money, duplicated.

    The fix is to let the UNIQUE constraint arbitrate: attempt the insert,
    catch IntegrityError, re-read the winner.
    """
    from app.domain.ledger import Leg, post_transaction

    cash, wallet = seeded_accounts["platform_cash"], seeded_accounts["user_wallet"]
    barrier = threading.Barrier(8)  # maximise the overlap
    results: list = []
    errors: list = []

    def worker() -> None:
        s = real_sessions()
        try:
            barrier.wait(timeout=10)
            txn = post_transaction(
                s,
                legs=[
                    Leg(cash, "debit", D("25.00")),
                    Leg(wallet, "credit", D("25.00")),
                ],
                idempotency_key="race-key",
                request_hash="same-hash",
            )
            s.commit()
            results.append(txn.id)
        except Exception as exc:
            errors.append(exc)
            s.rollback()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(8)))

    assert not errors, f"no thread should error: {errors}"
    assert len(set(results)) == 1, "all threads must see the same transaction id"

    from app.models import Transaction

    verify = real_sessions()
    count = verify.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.memo != "seed")
    )
    assert count == 1, "exactly one transaction may exist"


def test_concurrent_reversals_produce_exactly_one(
    engine, real_sessions, seeded_accounts
):
    """Two threads reverse the same transaction simultaneously.

    A SELECT COUNT check loses this race. The UNIQUE constraint on
    transactions.reverses_id wins it.
    """
    from app.domain.ledger import Leg, post_transaction, reverse_transaction

    setup = real_sessions()
    original = post_transaction(
        setup,
        legs=[
            Leg(seeded_accounts["platform_cash"], "debit", D("40.00")),
            Leg(seeded_accounts["user_wallet"], "credit", D("40.00")),
        ],
    )
    setup.commit()
    original_id = original.id

    barrier = threading.Barrier(2)
    succeeded: list = []
    rejected: list = []

    def worker() -> None:
        s = real_sessions()
        try:
            barrier.wait(timeout=10)
            rev = reverse_transaction(s, transaction_id=original_id)
            s.commit()
            succeeded.append(rev.id)
        except Exception as exc:
            s.rollback()
            rejected.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: worker(), range(2)))

    assert len(succeeded) == 1, "exactly one reversal must commit"
    assert len(rejected) == 1, "the loser must be rejected, not silently ignored"


def test_hot_account_stays_balanced_under_load(engine, real_sessions, seeded_accounts):
    """Many threads all touching the same account.

    This is the contention case that a mutable balance column cannot survive
    without serialising every writer. With an append-only journal it should
    just work — and the trial balance proves it.
    """
    from app.db import serializable_transaction
    from app.domain.ledger import Leg, post_transaction, trial_balance

    cash, wallet = seeded_accounts["platform_cash"], seeded_accounts["user_wallet"]
    posted = 0
    lock = threading.Lock()

    def worker(_n: int) -> None:
        nonlocal posted
        for _ in range(10):
            serializable_transaction(
                lambda s: post_transaction(
                    s,
                    legs=[
                        Leg(cash, "debit", D("1.00")),
                        Leg(wallet, "credit", D("1.00")),
                    ],
                )
            )
            with lock:
                posted += 1

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(worker, range(10)))

    assert posted == 100
    verify = real_sessions()
    assert trial_balance(verify) == D("0")


def test_read_modify_write_cannot_overdraw(engine, real_sessions, seeded_accounts):
    """The classic race: check balance, then post if sufficient.

    Two threads each see a balance of 100 and each withdraw 100. Under READ
    COMMITTED both succeed and the account goes to -100. Under SERIALIZABLE
    one is aborted with 40001.

    Only enable this once you have implemented a balance-constrained
    withdrawal path. It is the single best demonstration in the project that
    you understand isolation levels.
    """
    pytest.skip("enable once withdraw() with an InsufficientFunds check exists")
