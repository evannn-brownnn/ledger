"""Health endpoint tests.

These pass right now, before you write any domain code. That is deliberate:
you should be able to `make up && make test-unit` on day one and see green,
which proves the whole toolchain works before you add any complexity.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_liveness_does_not_touch_the_database():
    """Liveness must succeed even with the database down.

    No database fixture is requested here, and that is the assertion.
    """
    with TestClient(create_app()) as client:
        resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_request_id_is_echoed():
    """Every response carries a correlation ID for log tracing."""
    with TestClient(create_app()) as client:
        resp = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"


def test_request_id_is_generated_when_absent():
    with TestClient(create_app()) as client:
        resp = client.get("/health/live")
    assert resp.headers.get("X-Request-ID")


def test_openapi_schema_is_served():
    """A broken schema means broken docs and broken client generation."""
    with TestClient(create_app()) as client:
        resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Ledger Service"


def test_metrics_endpoint():
    with TestClient(create_app()) as client:
        client.get("/health/live")
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"ledger_http_requests_total" in resp.content


def test_unknown_route_returns_404_envelope():
    with TestClient(create_app()) as client:
        resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
