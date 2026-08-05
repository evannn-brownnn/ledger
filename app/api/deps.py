"""Shared FastAPI dependencies.

Dependencies are how FastAPI does inversion of control: you declare what a
route needs, and the framework supplies it. The big practical win is that
tests can override any dependency without monkeypatching.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.errors import AuthenticationError
from app.config import Settings, get_settings
from app.db import get_session

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False so a missing header raises our AuthenticationError (and
# therefore our JSON envelope) instead of FastAPI's default {"detail": ...}
# 403 from HTTPBearer itself.
_bearer_scheme = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
    settings: SettingsDep,
) -> None:
    if credentials is None or credentials.credentials not in settings.api_keys:
        raise AuthenticationError()


async def idempotency_key(
    key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Client-generated unique key. Retrying with the same key and "
                "the same body returns the original result instead of "
                "creating a duplicate. Use a UUID."
            ),
            max_length=128,
        ),
    ] = None,
) -> str | None:
    return key


IdempotencyKeyDep = Annotated[str | None, Depends(idempotency_key)]


async def request_fingerprint(request: Request) -> str:
    """SHA-256 of the canonicalised request body.

    Stored alongside the idempotency key so that reusing a key with a
    *different* payload can be detected and rejected. Sorting keys makes the
    hash stable regardless of JSON field ordering.
    """
    raw = await request.body()
    if not raw:
        return hashlib.sha256(b"").hexdigest()
    try:
        canonical = json.dumps(
            json.loads(raw), sort_keys=True, separators=(",", ":")
        ).encode()
    except json.JSONDecodeError:
        canonical = raw
    return hashlib.sha256(canonical).hexdigest()


FingerprintDep = Annotated[str, Depends(request_fingerprint)]
