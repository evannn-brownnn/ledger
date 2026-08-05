"""Translate domain exceptions into HTTP responses.

This is the only place in the codebase that knows both vocabularies. Domain
code raises meaning; this maps meaning to status codes and a stable JSON
error envelope.

The envelope is deliberately boring and consistent:

    {"error": {"code": "unbalanced_transaction",
               "message": "debits 100.00 != credits 99.99",
               "request_id": "..."}}

Clients can switch on `code` forever; `message` is for humans and may change.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from app.domain.errors import (
    AccountNotFound,
    AlreadyReversed,
    CannotReverseReversal,
    CurrencyMismatch,
    IdempotencyKeyConflict,
    InsufficientFunds,
    InvalidPosting,
    LedgerError,
    TransactionNotFound,
    UnbalancedTransaction,
)
from app.observability import get_logger, request_id_ctx

log = get_logger("api.errors")


class AuthenticationError(Exception):
    """Missing or invalid API key.

    Deliberately not a LedgerError subclass: authentication is an API-layer
    concern (like request validation), not a ledger rule, so it gets its own
    exception type and handler rather than being folded into the domain
    hierarchy.
    """


# 422 for semantic rejections the client could fix by sending different data.
# 404 for things that do not exist. 409 for state conflicts. 400 is reserved
# for genuinely malformed requests, which FastAPI handles before we see them.
STATUS_MAP: dict[type[LedgerError], int] = {
    InvalidPosting: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnbalancedTransaction: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CurrencyMismatch: status.HTTP_422_UNPROCESSABLE_CONTENT,
    IdempotencyKeyConflict: status.HTTP_422_UNPROCESSABLE_CONTENT,
    AccountNotFound: status.HTTP_404_NOT_FOUND,
    TransactionNotFound: status.HTTP_404_NOT_FOUND,
    AlreadyReversed: status.HTTP_409_CONFLICT,
    CannotReverseReversal: status.HTTP_409_CONFLICT,
    InsufficientFunds: status.HTTP_409_CONFLICT,
}


def _envelope(code: str, message: str, http_status: int) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id_ctx.get(),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(LedgerError)
    async def _domain(_request: Request, exc: LedgerError) -> JSONResponse:
        http_status = STATUS_MAP.get(type(exc), status.HTTP_422_UNPROCESSABLE_CONTENT)
        log.info("domain_rejection", code=exc.code, detail=str(exc))
        return _envelope(exc.code, str(exc), http_status)

    @app.exception_handler(RequestValidationError)
    async def _validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic's raw error list is useful; pass it through under a
        # stable code so clients can parse field-level problems.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "request body failed validation",
                    "fields": exc.errors(),
                    "request_id": request_id_ctx.get(),
                }
            },
        )

    @app.exception_handler(AuthenticationError)
    async def _authentication(
        _request: Request, _exc: AuthenticationError
    ) -> JSONResponse:
        return _envelope(
            "unauthorized",
            "missing or invalid API key",
            status.HTTP_401_UNAUTHORIZED,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_request: Request, exc: IntegrityError) -> JSONResponse:
        # Reaching here means a constraint fired that the domain layer did
        # not anticipate. That is a bug worth seeing in full, but the client
        # gets a generic conflict rather than your schema internals.
        log.error("unhandled_integrity_error", detail=str(exc.orig))
        return _envelope(
            "conflict",
            "the request conflicts with existing data",
            status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(OperationalError)
    async def _operational(_request: Request, exc: OperationalError) -> JSONResponse:
        # Serialization failures that exhausted their retries land here.
        # 503 with Retry-After tells a well-behaved client to try again,
        # which is exactly the right outcome.
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate in {"40001", "40P01"}:
            log.warning("serialization_failure_exhausted", sqlstate=sqlstate)
            resp = _envelope(
                "retry_later",
                "the request conflicted with a concurrent transaction; retry",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            resp.headers["Retry-After"] = "1"
            return resp
        log.exception("database_operational_error")
        return _envelope(
            "database_unavailable",
            "the database is unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, _exc: Exception) -> JSONResponse:
        # Never leak a stack trace to a client. Log it in full, return a
        # correlation ID the user can quote to support.
        log.exception("unhandled_exception")
        return _envelope(
            "internal_error",
            "an unexpected error occurred",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
