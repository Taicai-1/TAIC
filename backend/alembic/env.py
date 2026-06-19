"""Alembic environment configuration.

Imports Base metadata and database URL from the application's database module
so that autogenerate can detect model changes.
"""

import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text
from alembic import context

# Ensure the backend package is importable (alembic runs from backend/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Base, get_database_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: alembic runs inside the app at startup;
    # the default (True) silenced every application logger after migrations.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database.

    Uses NullPool so migration connections don't interfere with the
    application's connection pool.
    """
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Prevent hanging on table locks during startup (e.g. ALTER TABLE on busy tables).
        # SET is session-scoped, so the timeouts survive the commit below.
        connection.execute(text("SET lock_timeout = '5s'"))
        connection.execute(text("SET statement_timeout = '30s'"))
        # CRITICAL: end the implicit (autobegin) transaction opened by the SET
        # statements. When alembic finds a transaction already active, it assumes
        # the caller owns it and never commits — every migration then silently
        # rolls back when the connection closes.
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
