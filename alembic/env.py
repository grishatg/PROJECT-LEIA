"""Alembic environment, wired to PROJECT-LEIA's models + database URL.

The DB URL is resolved the same way the app resolves it (explicit > .env >
local SQLite), so migrations always target the same database the app uses.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from leia.db import resolve_database_url
from leia.models import Base

config = context.config

# Resolve the URL from the app's settings rather than hardcoding it in alembic.ini.
config.set_main_option("sqlalchemy.url", resolve_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI needed)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-friendly ALTERs
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and apply)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-friendly ALTERs
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
