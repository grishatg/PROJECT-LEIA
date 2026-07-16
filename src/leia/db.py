"""Database engine, sessions, and schema creation.

SQLite by default (``data/leia.db``); set ``DATABASE_URL`` to use Postgres later.

Hosted Postgres (Supabase behind its Supavisor pooler) and a free-tier host that
sleeps mean connections drop out from under us. Two defences live here:

- ``make_engine`` enables ``pool_pre_ping`` so a stale/closed connection is
  detected and replaced transparently instead of surfacing a pool error on the
  first query after an idle spell.
- ``upgrade_database`` retries the boot migration with backoff, and turns the
  raw psycopg traceback into a plain-English diagnosis (see
  ``describe_connection_error``) — the common cause is a *paused* Supabase
  project, which a non-technical owner can un-pause in one click.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from leia.models import Base

DATA_DIR = Path("data")
DEFAULT_DB_FILE = DATA_DIR / "leia.db"


class DatabaseUnavailable(RuntimeError):
    """The database could not be reached. Carries a human-readable explanation."""


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
    if resolved.startswith("sqlite"):
        # Local file/in-memory DB: no network, no pool to keep warm.
        return create_engine(
            resolved,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False},
        )
    # Hosted Postgres (e.g. Supabase pooler) reachable over a network that may
    # drop idle connections. pool_pre_ping validates a connection before handing
    # it out (silently reconnecting if it's dead); pool_recycle retires
    # long-lived connections before the server/pooler closes them itself.
    return create_engine(
        resolved,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


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


def _redact(url: str) -> str:
    """Hide the password in a connection string before showing it to a human."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, _, tail = rest.partition("@")
    if ":" in creds:
        user, _, _pw = creds.partition(":")
        creds = f"{user}:***"
    return f"{scheme}://{creds}@{tail}"


def is_connection_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a *reach the server* failure (vs. a SQL error).

    We only want to retry / soften these; a genuine migration or query error
    should still surface loudly.
    """
    if isinstance(exc, (OperationalError, InterfaceError)):
        return True
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    text = str(exc).lower()
    signatures = (
        "tenant or user not found",
        "tenant/user",
        "enotfound",
        "could not connect",
        "connection refused",
        "connection failed",
        "server closed the connection",
        "timeout expired",
        "could not translate host name",
        "name or service not known",
        "no route to host",
    )
    return any(s in text for s in signatures)


def describe_connection_error(exc: BaseException, url: str | None = None) -> str:
    """Turn a raw driver error into a short, actionable explanation.

    The owner is non-technical, so we name the likely cause and the one-click
    fix rather than dumping a psycopg traceback.
    """
    text = str(exc).lower()
    target = _redact(url) if url else "the database"
    lines: list[str]

    if "tenant or user not found" in text or "tenant/user" in text or "enotfound" in text:
        # Supabase's pooler rejects logins for a project that isn't currently
        # serving — almost always a *paused* free-tier project.
        lines = [
            "Can't reach the Supabase database — it looks PAUSED.",
            "Supabase free-tier projects auto-pause after ~7 days idle, and a paused "
            "project is rejected by the connection pooler with "
            "'tenant/user ... not found'.",
            "Fix: open https://supabase.com/dashboard, pick this project, and click "
            "'Restore'/'Resume'. It takes a minute to come up, then redeploy (or just "
            "reload the app — it reconnects on its own).",
        ]
    elif "password authentication failed" in text:
        lines = [
            "Database rejected the password.",
            "Fix: check the password inside DATABASE_URL. If it contains special "
            "characters they must be percent-encoded. Reset it in Supabase → Project "
            "Settings → Database if unsure.",
        ]
    elif "could not translate host name" in text or "name or service not known" in text:
        lines = [
            "Database host name couldn't be resolved.",
            "Fix: check the host in DATABASE_URL. For Render, use the Supabase "
            "*pooler* host (…pooler.supabase.com) with the "
            "'postgres.<project-ref>' username — the direct db.<ref>.supabase.co host "
            "is IPv6-only and won't resolve there.",
        ]
    else:
        lines = [
            f"Can't reach {target}.",
            "The database may be paused, still starting up, or unreachable from here. "
            "Check that it's running and that DATABASE_URL is correct, then try again.",
        ]

    if url:
        lines.append(f"(connection target: {_redact(url)})")
    return "\n".join(lines)


def upgrade_database(
    revision: str = "head",
    *,
    retries: int = 5,
    base_delay: float = 2.0,
    on_retry=None,
) -> None:
    """Create/upgrade the real database via Alembic migrations (and stamp version).

    Retries transient connection failures with exponential backoff — a hosted DB
    that is still waking up (e.g. a just-resumed Supabase project reporting
    ``COMING_UP``) typically becomes reachable within the retry window. A
    persistent failure is re-raised as ``DatabaseUnavailable`` carrying a
    plain-English diagnosis instead of a raw driver traceback.

    ``on_retry(attempt, delay, exc)`` is an optional progress callback.
    """
    from alembic import command

    url = resolve_database_url()
    cfg = _alembic_config()
    last_exc: BaseException | None = None

    for attempt in range(1, retries + 1):
        try:
            command.upgrade(cfg, revision)
            return
        except Exception as exc:  # noqa: BLE001 - inspect, then re-raise appropriately
            if not is_connection_error(exc):
                raise
            last_exc = exc
            if attempt >= retries:
                break
            delay = base_delay * (2 ** (attempt - 1))
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            time.sleep(delay)

    raise DatabaseUnavailable(describe_connection_error(last_exc, url)) from last_exc


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
