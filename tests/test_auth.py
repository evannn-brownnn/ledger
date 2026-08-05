"""Auth mechanism tests.

These exercise `require_api_key` against a throwaway route, independent of
the real ledger endpoints — wiring it onto `app/api/v1/ledger.py` is a
separate step (see docs/MILESTONES.md, milestone 4) that touches a file the
owner is actively working in for milestones 1 and 3. No database is needed
here, so this runs under `make test-unit`.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_api_key
from app.api.errors import register_exception_handlers
from app.config import Settings, get_settings


def _client(api_keys: list[str]) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    def _protected() -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[get_settings] = lambda: Settings(api_keys=api_keys)
    return TestClient(app)


def test_missing_key_is_rejected():
    client = _client(api_keys=["valid-key"])
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_wrong_key_is_rejected():
    client = _client(api_keys=["valid-key"])
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


def test_correct_key_is_accepted():
    client = _client(api_keys=["valid-key"])
    resp = client.get("/protected", headers={"Authorization": "Bearer valid-key"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_key_rotation_accepts_either_key():
    """A list of valid keys, not one, so a key can be rotated without downtime."""
    client = _client(api_keys=["old-key", "new-key"])
    for key in ("old-key", "new-key"):
        resp = client.get("/protected", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200


def test_no_api_keys_configured_rejects_everything():
    """An empty allowlist must fail closed, not open."""
    client = _client(api_keys=[])
    resp = client.get("/protected", headers={"Authorization": "Bearer anything"})
    assert resp.status_code == 401
