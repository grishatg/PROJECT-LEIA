"""Alembic environment, wired to PROJECT-LEIA's models + database URL.

The DB URL is resolved the same way the app resolves it (explicit > .env >
local SQLite) and passed straight to the engine — never through ConfigParser,
so passwords containing ``%`` (e.g. percent-encoded special characters) don't
break interpolation.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from leia.db import resolve_database_url
from leia.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate' support.
target_metadata = Base.metadata

# Resolve once, here, rather than storing it in alembic's ConfigParser (which
# would try to interpolate any '%' in the URL/password and crash).
DATABASE_URL = resolve_database_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI needed)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-friendly ALTERs
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and apply)."""
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool, future=True)
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
