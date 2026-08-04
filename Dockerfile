# Multi-stage build.
#
#   target=dev  -> includes dev dependencies, used by docker-compose
#   target=prod -> slim runtime image, non-root, no build toolchain
#
# The layer ordering matters: dependencies are installed before the source
# is copied, so editing your code does not invalidate the (slow) dependency
# layer. This is the single biggest Docker build-speed lever.

# -----------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# Runtime OS packages only. psycopg[binary] ships its own libpq, so we do
# not need libpq-dev here; curl is for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
FROM base AS deps

COPY pyproject.toml ./
# Install only the dependency metadata first. `pip install .` would need the
# source tree, so we resolve deps from pyproject via a throwaway install.
RUN pip install --upgrade pip setuptools wheel \
    && pip install ".[dev]" 2>/dev/null || pip install \
        "fastapi>=0.115" "uvicorn[standard]>=0.32" "sqlalchemy>=2.0.36" \
        "alembic>=1.14" "psycopg[binary,pool]>=3.2" "pydantic>=2.10" \
        "pydantic-settings>=2.6" "structlog>=24.4" "prometheus-client>=0.21" \
        "tenacity>=9.0"

# -----------------------------------------------------------------------------
FROM deps AS dev

# Dev tooling on top of runtime deps.
RUN pip install pytest pytest-cov pytest-asyncio httpx ruff mypy locust

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# -----------------------------------------------------------------------------
FROM base AS prod

# Copy the resolved site-packages from the deps stage rather than
# reinstalling, and leave the build toolchain behind.
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Never run as root in a production image.
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# No --reload in production. Worker count is set via env so you can tune it
# without rebuilding; 2 workers is a sane default for a small container.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
