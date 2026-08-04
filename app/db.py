"""Database engine, session lifecycle, and transaction helpers.

Three things worth understanding here, because they are the parts that bite
people coming from scripting into production services:

1. The engine is a *pool*, created once per process. Creating engines
   per-request is the classic mistake and will exhaust Postgres connections.

2. A request gets exactly one session and one transaction. It commits at the
   end or rolls back on exception. Never commit inside domain logic.

3. Under SERIALIZABLE isolation, Postgres will abort transactions with
   SQLSTATE 40001 when it detects a dependency cycle. That is not a bug and
   not your fault — it is the isolation level working. The correct response
   is to retry the whole transaction, which `serializable_transaction`
   handles for you.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings

log = logging.getLogger(__name__)

# Postgres SQLSTATE codes we treat as "retry the whole transaction".
SERIALIZATION_FAILURE = "40001"
DEADLOCK_DETECTED = "40P01"
RETRYABLE_SQLSTATES = frozenset({SERIALIZATION_FAILURE, DEADLOCK_DETECTED})


def _build_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=settings.db_pool_recycle_s,
        # Checks the connection is alive before handing it out. Costs one
        # tiny round trip and eliminates a whole category of "server closed
        # the connection unexpectedly" errors after network blips.
        pool_pre_ping=True,
        echo=settings.db_echo,
        # Send parameterised statements natively rather than emulating.
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_session_defaults(dbapi_conn: Any, _record: Any) -> None:
        """Applied to every new physical connection.

        A statement timeout is a cheap, extremely effective safety net: a
        pathological query gets killed instead of holding locks forever and
        cascading into an outage.
        """
        with dbapi_conn.cursor() as cur:
            cur.execute("SET statement_timeout = '15s'")
            cur.execute("SET idle_in_transaction_session_timeout = '30s'")
            cur.execute("SET lock_timeout = '5s'")
            # Timestamps are stored and compared in UTC, always.
            cur.execute("SET timezone = 'UTC'")

    return engine


engine: Engine = _build_engine()

# expire_on_commit=False keeps ORM objects usable after commit, which means
# your route can still read `txn.id` to build the response. Without it you
# get a surprise lazy-load against a closed transaction.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def _is_retryable(exc: BaseException) -> bool:
    """True for Postgres serialization failures and deadlocks."""
    if isinstance(exc, (DBAPIError, OperationalError)):
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        return sqlstate in RETRYABLE_SQLSTATES
    return False


@contextmanager
def session_scope(*, serializable: bool = False) -> Iterator[Session]:
    """One session, one transaction, guaranteed cleanup.

    Args:
        serializable: run the transaction at SERIALIZABLE isolation. Use
            this for any operation whose correctness depends on reading
            state and then writing based on it — for example, checking a
            balance before allowing a withdrawal. READ COMMITTED (the
            default) does *not* protect you there.
    """
    session = SessionLocal()
    try:
        if serializable:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def serializable_transaction[T](fn: Callable[[Session], T]) -> T:
    """Run `fn` in a SERIALIZABLE transaction, retrying on 40001/40P01.

    Usage:

        result = serializable_transaction(
            lambda s: post_transaction(s, legs=legs, ...)
        )

    The retry has exponential backoff with jitter. Jitter matters: without
    it, two conflicting transactions retry in lockstep and keep colliding.

    IMPORTANT: `fn` must be idempotent with respect to in-memory state,
    because it may run several times. Do not mutate objects outside the
    session inside it.
    """
    settings = get_settings()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(settings.db_serialization_retries),
        wait=wait_exponential_jitter(initial=0.01, max=0.5),
        reraise=True,
    )
    def _attempt() -> T:
        with session_scope(serializable=True) as session:
            return fn(session)

    return _attempt()


def get_session() -> Iterator[Session]:
    """FastAPI dependency. One session per request.

    Yielded rather than returned so FastAPI runs the teardown after the
    response is produced.
    """
    with session_scope() as session:
        yield session


def check_database() -> bool:
    """Cheap liveness probe used by the readiness endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        log.exception("database health check failed")
        return False
