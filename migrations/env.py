"""Alembic environment.

Wired to read the database URL from your application settings rather than
alembic.ini, so there is exactly one source of truth for connection config.

`compare_type` and `compare_server_default` are enabled because without them
autogenerate silently misses column type changes — you get a migration that
looks fine and does nothing.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at the app's settings-derived URL.
config.set_main_option("sqlalchemy.url", str(get_settings().database_url))

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    """Filter what autogenerate considers.

    Once you add partitioning, individual partition tables show up here as
    unexpected tables and autogenerate will try to drop them. Filtering them
    out by naming convention (e.g. transactions_2026_01) avoids that.
    """
    return not (type_ == "table" and "_20" in name)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it.

    Useful when a DBA has to review or apply changes by hand:
        alembic upgrade head --sql
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # migrations are short-lived; no pool needed
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            # Wrap the whole migration in one transaction. Postgres has
            # transactional DDL, so a failed migration rolls back cleanly
            # instead of leaving a half-migrated schema.
            transaction_per_migration=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
