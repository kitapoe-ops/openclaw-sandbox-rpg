"""Alembic environment.

Pulls the database URL from ``backend.config.settings.database_url`` (or
``SANDBOX_DATABASE_URL`` env var if set). Uses the synchronous driver form
(asyncpg / aiosqlite → psycopg2 / sqlite3) since Alembic migrations run
synchronously.

Imports ``Base.metadata`` from ``backend.orm`` for autogenerate support.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# --- Make the project root importable so `backend.*` resolves ---------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- Alembic Config ----------------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Database URL: prefer env, fall back to settings -------------------------
def _resolve_database_url() -> str:
    """Pick a sync-compatible database URL.

    Order:
    1. ``SANDBOX_DATABASE_URL`` env var (explicit override)
    2. ``alembic.ini`` sqlalchemy.url
    3. ``backend.config.settings.database_url`` (Postgres by default)
    """
    env_url = os.environ.get("SANDBOX_DATABASE_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    # Fall back to project settings
    from backend.config import settings
    return settings.database_url


def _to_sync_url(url: str) -> str:
    """Strip async driver suffixes so Alembic (sync) can use it."""
    return url.replace("+asyncpg", "").replace("+aiosqlite", "")


config.set_main_option("sqlalchemy.url", _to_sync_url(_resolve_database_url()))

# --- Target metadata (for autogenerate) --------------------------------------
# Import the Base from our ORM module. Defer to runtime so this file can be
# imported without dragging in pydantic / full app context.
try:
    from backend.orm import Base
    target_metadata = Base.metadata
except Exception as exc:  # noqa: BLE001
    # If the import fails (e.g. running alembic before installing deps),
    # fall back to metadata-less migrations.
    import warnings
    warnings.warn(f"alembic env.py: could not import backend.orm ({exc}); "
                  f"autogenerate will be disabled.")
    target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        url = config.get_main_option("sqlalchemy.url") or ""
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
