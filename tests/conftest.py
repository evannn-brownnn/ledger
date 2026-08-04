"""Shared test fixtures.

The important pattern here is the transactional-rollback fixture. Each test
runs inside a transaction that is rolled back afterwards, so tests are
isolated without the cost of recreating the schema between them. This is the
standard way to get fast, independent database tests.

Tests requiring Postgres are marked `integration`. Run just the fast ones
with:  pytest -m "not integration"
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

D = Decimal

TEST_DATABASE_URL = os.getenv(
    "LEDGER_TEST_DATABASE_URL",
    "postgresql+psycopg://ledger:ledger@localhost:5433/ledger_test",
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """One engine for the whole test session."""
    eng = create_engine(TEST_DATABASE_URL, poolclass=None, future=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("test database unavailable; run `make test`")
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def _schema(engine: Engine) -> Iterator[None]:
    """Create the schema once per session.

    Deliberately uses Alembic rather than create_all, so the tests exercise
    the same migrations that will run in production. A migration that works
    in dev but fails on a fresh database is a classic deploy-night surprise;
    this catches it.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")
    yield
    command.downgrade(cfg, "base")


@pytest.fixture()
def session(engine: Engine, _schema: None) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back.

    The nested-transaction listener re-opens a SAVEPOINT whenever the code
    under test commits, so domain code can call commit() freely and the
    outer transaction still rolls everything back at the end.
    """
    connection = engine.connect()
    trans = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, future=True)
    sess = factory()
    sess.begin_nested()

    @event.listens_for(sess, "after_transaction_end")
    def _restart_savepoint(sess_: Session, trans_: object) -> None:
        if getattr(trans_, "nested", False) and not getattr(
            getattr(trans_, "_parent", None), "nested", False
        ):
            sess_.begin_nested()

    try:
        yield sess
    finally:
        sess.close()
        trans.rollback()
        connection.close()


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    """API client whose requests share the test's rolled-back session."""
    from app.db import get_session
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def accounts(session: Session) -> dict[str, object]:
    """A minimal chart of accounts used across the suite.

    Uncomment once your models exist.

        from app.models import Account
        book = {
            "user_wallet":   "credit",   # you owe the user -> liability
            "platform_cash": "debit",    # cash you hold    -> asset
            "fee_revenue":   "credit",   # income
            "reserve":       "debit",    # asset
        }
        made = {}
        for name, normal in book.items():
            a = Account(name=name, normal_balance=normal, currency="USD")
            session.add(a)
            made[name] = a
        session.flush()
        return made
    """
    pytest.skip("define your Account model, then enable this fixture")


@pytest.fixture()
def eur_account(session: Session) -> object:
    """A non-USD account, used to prove cross-currency postings are rejected.

    from app.models import Account
    a = Account(name="eur_wallet", normal_balance="credit", currency="EUR")
    session.add(a)
    session.flush()
    return a
    """
    pytest.skip("define your Account model, then enable this fixture")


@pytest.fixture()
def seeded_accounts(engine) -> dict[str, str]:
    """Committed accounts for the concurrency suite.

    Distinct from `accounts`: those live inside a rolled-back transaction and
    are invisible to other connections. Concurrency tests need real, committed
    rows that every thread can see. Returns {name: account_id}.

        from sqlalchemy.orm import sessionmaker
        from app.models import Account

        factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        s = factory()
        made = {}
        for name, normal in [("platform_cash", "debit"), ("user_wallet", "credit")]:
            a = Account(name=f"{name}-{uuid.uuid4()}", normal_balance=normal)
            s.add(a)
            s.flush()
            made[name] = a.id
        s.commit()
        s.close()
        yield made
        # teardown: delete the rows you created
    """
    pytest.skip("define your Account model, then enable this fixture")
