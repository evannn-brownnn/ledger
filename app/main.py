"""Application entry point.

`create_app()` is a factory rather than a module-level app object. That
matters for testing: each test can build a fresh app with different settings
instead of fighting import-time global state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.v1 import ledger as ledger_v1
from app.config import get_settings
from app.db import check_database, engine
from app.observability import (
    RequestContextMiddleware,
    configure_logging,
    get_logger,
    metrics_response,
)

log = get_logger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown.

    Startup deliberately does NOT run migrations. Migrations are a separate,
    explicit deploy step — having N replicas race to migrate on boot is a
    reliable way to corrupt a schema.
    """
    settings = get_settings()
    configure_logging()
    log.info(
        "starting",
        app=settings.app_name,
        environment=settings.environment,
        db_reachable=check_database(),
    )
    yield
    engine.dispose()
    log.info("stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Ledger Service",
        version="0.1.0",
        description=(
            "An immutable, double-entry ledger.\n\n"
            "**Invariants**\n"
            "- Every transaction balances: sum(debits) == sum(credits).\n"
            "- Nothing is ever updated or deleted; corrections are reversals.\n"
            "- Balances are derived from the journal, never stored.\n"
            "- Postings are idempotent when an `Idempotency-Key` is supplied."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # Order matters: middleware added last runs outermost. Request context
    # should wrap everything so every log line and metric is correlated.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*", "Idempotency-Key"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(ledger_v1.router, prefix=settings.api_prefix)

    if settings.metrics_enabled:
        # Not under the versioned prefix — metrics are infrastructure, not
        # part of the public API contract.
        app.add_route(
            "/metrics", lambda _r: metrics_response(), include_in_schema=False
        )

    return app


app = create_app()
