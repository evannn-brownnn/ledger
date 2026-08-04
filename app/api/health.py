"""Liveness and readiness endpoints.

These are distinct on purpose and orchestrators treat them differently:

  /health/live   Is the process alive? Must not touch the database. If this
                 fails, the container gets killed and restarted. Making it
                 depend on Postgres means a brief database blip restarts
                 every one of your containers — a self-inflicted outage.

  /health/ready  Can this instance serve traffic? Checks dependencies. If it
                 fails, the load balancer stops routing here but the process
                 keeps running and can recover.

Getting this distinction wrong is one of the most common production
mistakes, and it only hurts you during an incident.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.schemas import HealthOut
from app.db import check_database

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthOut)
async def live() -> HealthOut:
    return HealthOut(status="ok", checks={"process": True})


@router.get("/health/ready", response_model=HealthOut)
async def ready(response: Response) -> HealthOut:
    db_ok = check_database()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(
        status="ok" if db_ok else "degraded",
        checks={"database": db_ok},
    )
