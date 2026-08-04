"""Application configuration.

Everything configurable lives here and comes from the environment. This is
the twelve-factor pattern: the same image runs in every environment, and
only the env vars differ.

pydantic-settings validates on startup, so a typo'd or missing variable
fails immediately and loudly rather than surfacing as a confusing error
three layers deep at request time.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEDGER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- identity ------------------------------------------------------------
    app_name: str = "ledger"
    environment: Literal["local", "ci", "staging", "production"] = "local"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    # --- database ------------------------------------------------------------
    database_url: PostgresDsn = Field(
        default="postgresql+psycopg://ledger:ledger@localhost:5432/ledger",  # type: ignore[arg-type]
        description="SQLAlchemy URL. Must use the psycopg (v3) driver.",
    )

    # Connection pool. Sized deliberately rather than left at defaults:
    # total connections across all workers must stay under Postgres'
    # max_connections (default 100), or you get intermittent failures
    # under load that are miserable to diagnose.
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_s: int = 10
    db_pool_recycle_s: int = 1800  # recycle before proxies/Postgres time out
    db_echo: bool = False  # set true to log every SQL statement

    # How many times to retry a transaction that Postgres aborted with a
    # serialization failure (SQLSTATE 40001). Under SERIALIZABLE isolation
    # these are normal and expected, not errors.
    db_serialization_retries: int = 3

    @field_validator("database_url")
    @classmethod
    def _require_psycopg3(cls, v: PostgresDsn) -> PostgresDsn:
        if "+psycopg2" in str(v):
            raise ValueError(
                "psycopg2 is not supported; use postgresql+psycopg:// (psycopg3)"
            )
        return v

    # --- http ----------------------------------------------------------------
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=list)

    # Reject request bodies larger than this. A ledger posting is small;
    # anything huge is either a bug or an attack.
    max_request_bytes: int = 1_048_576  # 1 MiB

    # --- observability -------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True

    # --- domain --------------------------------------------------------------
    # Currencies the ledger will accept. Postings that mix currencies, or use
    # one not in this list, must be rejected.
    supported_currencies: list[str] = Field(default_factory=lambda: ["USD"])

    # Scale used for all monetary amounts. NUMERIC(20, 4) gives you four
    # decimal places, which covers sub-cent fee arithmetic without floats.
    amount_scale: int = 4

    # How long an idempotency key stays valid. Replaying a key after this
    # window should be treated as a new request.
    idempotency_ttl_hours: int = 24


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor.

    lru_cache makes this a singleton so config is parsed once. In tests you
    can override it with `app.dependency_overrides` or by calling
    `get_settings.cache_clear()` after mutating the environment.
    """
    return Settings()
