"""Shared test fixtures.

Tests run OFFLINE and FREE: an in-memory SQLite DB and a fake Anthropic client.
No real network calls, no Claude spend.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from leia.models import Base


@pytest.fixture()
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()


# ── Fake Anthropic client (used by scoring/drafting tests in Phase 1) ──────


class _FakeMessages:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeAnthropic ran out of canned responses")
        return self._responses.pop(0)


class FakeAnthropic:
    """Minimal stand-in for anthropic.Anthropic with canned responses.

    Phase 1's llm/client.py will define exactly how responses are shaped; this
    just provides the call surface so tests stay offline.
    """

    def __init__(self, responses: list | None = None):
        self.messages = _FakeMessages(responses or [])


@pytest.fixture()
def fake_anthropic() -> type[FakeAnthropic]:
    return FakeAnthropic
