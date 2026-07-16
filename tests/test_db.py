"""Tests for engine hardening + the paused-database diagnosis.

All offline: engines are constructed (never connected), and the Alembic upgrade
is monkeypatched so no real database is touched.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from leia import db
from leia.db import (
    DatabaseUnavailable,
    describe_connection_error,
    is_connection_error,
    make_engine,
    upgrade_database,
)

# The exact rejection Supabase's pooler returns for a paused project.
PAUSED_ERR = OperationalError(
    "SELECT 1",
    {},
    Exception(
        "connection failed: FATAL:  (ENOTFOUND) tenant/user "
        "postgres.pentsdzmekmjgpnaulfr not found"
    ),
)


def test_sqlite_engine_has_no_pre_ping():
    """Local SQLite has no network to babysit — pre_ping stays off."""
    engine = make_engine("sqlite:///:memory:")
    assert engine.pool._pre_ping is False
    engine.dispose()


def test_postgres_engine_enables_pre_ping_and_recycle():
    """Hosted Postgres gets pre_ping + recycle so idle-dropped connections heal."""
    engine = make_engine(
        "postgresql+psycopg://postgres.ref:pw@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"
    )
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 1800
    engine.dispose()


def test_is_connection_error_recognizes_paused_pooler():
    assert is_connection_error(PAUSED_ERR) is True


def test_is_connection_error_ignores_plain_errors():
    assert is_connection_error(ValueError("bad migration script")) is False


def test_describe_paused_project_is_actionable():
    msg = describe_connection_error(PAUSED_ERR, "postgresql+psycopg://u:secret@host/db")
    assert "PAUSED" in msg
    assert "supabase.com/dashboard" in msg
    # Password must never appear in a user-facing message.
    assert "secret" not in msg
    assert "***" in msg


def test_describe_bad_password():
    err = OperationalError("x", {}, Exception("FATAL: password authentication failed"))
    msg = describe_connection_error(err, "postgresql+psycopg://u:pw@host/db")
    assert "password" in msg.lower()


def test_upgrade_retries_then_succeeds(monkeypatch):
    """A DB still waking up (transient) is retried until it answers."""
    calls = {"n": 0}

    def fake_upgrade(cfg, revision):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PAUSED_ERR
        return None

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)
    monkeypatch.setattr(db, "resolve_database_url", lambda url=None: "postgresql+psycopg://u:pw@h/d")

    retries: list[int] = []
    upgrade_database(retries=5, base_delay=0.01, on_retry=lambda a, d, e: retries.append(a))

    assert calls["n"] == 3
    assert retries == [1, 2]  # two retries before the third attempt succeeded


def test_upgrade_gives_up_with_friendly_error(monkeypatch):
    """A persistently unreachable DB raises DatabaseUnavailable, not a raw traceback."""

    def fake_upgrade(cfg, revision):
        raise PAUSED_ERR

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)
    monkeypatch.setattr(db, "resolve_database_url", lambda url=None: "postgresql+psycopg://u:pw@h/d")

    with pytest.raises(DatabaseUnavailable) as exc:
        upgrade_database(retries=3, base_delay=0.01)
    assert "PAUSED" in str(exc.value)


def test_upgrade_does_not_swallow_real_migration_errors(monkeypatch):
    """A genuine (non-connection) failure surfaces immediately, unwrapped."""
    calls = {"n": 0}

    def fake_upgrade(cfg, revision):
        calls["n"] += 1
        raise ValueError("column already exists")

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    monkeypatch.setattr(db, "resolve_database_url", lambda url=None: "postgresql+psycopg://u:pw@h/d")

    with pytest.raises(ValueError, match="column already exists"):
        upgrade_database(retries=3, base_delay=0.01)
    assert calls["n"] == 1  # not retried
