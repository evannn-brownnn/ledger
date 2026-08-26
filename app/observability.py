"""Structured logging, request correlation, and Prometheus metrics.

Why this exists at all: when a money-moving service misbehaves at 3am, the
only thing that saves you is being able to answer "what happened to request
X". Unstructured print() logs cannot answer that. Structured logs with a
correlation ID can.

This module is complete — you should not need to change it, only use it.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

import structlog
from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.typing import EventDict, Processor

from app.config import get_settings

# A ContextVar is the async-safe equivalent of thread-local storage. It lets
# the logger pick up the current request's ID without every function having
# to pass it down.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


# --- metrics -----------------------------------------------------------------
# Label cardinality is the thing to be careful with: never label by anything
# unbounded (user id, account id, raw path). Use the route *template*.

REQUESTS = Counter(
    "ledger_http_requests_total",
    "HTTP requests",
    ["method", "route", "status"],
)
LATENCY = Histogram(
    "ledger_http_request_duration_seconds",
    "Request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
POSTINGS = Counter(
    "ledger_postings_total",
    "Journal entries appended",
    ["outcome"],  # committed | rejected | replayed
)
RETRIES = Counter(
    "ledger_serialization_retries_total",
    "Transactions retried after a Postgres serialization failure",
)


def _add_request_id(_logger: object, _name: str, event_dict: EventDict) -> EventDict:
    event_dict["request_id"] = request_id_ctx.get()
    return event_dict


def configure_logging() -> None:
    """Wire stdlib logging and structlog to the same output.

    Call once, at startup. Libraries log through stdlib; our code logs
    through structlog; both end up as the same JSON on stdout.
    """
    settings = get_settings()

    # Annotated rather than inferred: the elements are heterogeneous (plain
    # functions and processor instances), so mypy widens the list to
    # list[object] and then rejects it where structlog wants processors.
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_request_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )
    # SQLAlchemy is extremely chatty at INFO. Leave it at WARNING unless
    # you are actively debugging SQL, in which case set LEDGER_DB_ECHO=true.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, time the request, emit one access log line.

    Honours an inbound X-Request-ID so a correlation ID from an upstream
    gateway or client is preserved end to end.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        log = get_logger("http")
        started = time.perf_counter()

        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            log.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
            )
            raise
        finally:
            elapsed = time.perf_counter() - started
            # Use the matched route template, not the raw path, so that
            # /accounts/{id} is one metric series rather than a million.
            route = request.scope.get("route")
            template = getattr(route, "path", request.url.path)
            REQUESTS.labels(request.method, template, str(status)).inc()
            LATENCY.labels(request.method, template).observe(elapsed)
            request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=status,
            duration_ms=round(elapsed * 1000, 2),
        )
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
