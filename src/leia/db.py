"""Database engine, sessions, and schema creation.

SQLite by default (``data/leia.db``); set ``DATABASE_URL`` to use Postgres later.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from leia.models import Base

DATA_DIR = Path("data")
DEFAULT_DB_FILE = DATA_DIR / "leia.db"


def resolve_database_url(url: str | None = None) -> str:
    """Resolve the database URL: explicit arg > settings/.env > local SQLite file."""
    if url:
        return url
    # Lazy import keeps db.py importable without a configured environment
    # and lets tests pass an explicit in-memory URL.
    from leia.config import get_settings

    settings = get_settings()
    if settings.database_url:
        return settings.database_url
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"


def make_engine(url: str | None = None, echo: bool = False) -> Engine:
    resolved = resolve_database_url(url)
    connect_args = {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    return create_engine(resolved, echo=echo, future=True, connect_args=connect_args)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db(engine: Engine | None = None) -> Engine:
    """Create all tables directly via the ORM metadata. Idempotent.

    Used by tests and programmatic callers (fast, no migration runner). The
    ``leia init-db`` CLI uses Alembic instead (see ``upgrade_database``) so the
    real database carries a migration version stamp.
    """
    engine = engine or make_engine()
    Base.metadata.create_all(engine)
    return engine


def _alembic_config():
    """Build an Alembic config resolved relative to the repo root (CWD-independent)."""
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    return cfg


def upgrade_database(revision: str = "head") -> None:
    """Create/upgrade the real database via Alembic migrations (and stamp version)."""
    from alembic import command

    command.upgrade(_alembic_config(), revision)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional session: commit on success, rollback on error, always close."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
