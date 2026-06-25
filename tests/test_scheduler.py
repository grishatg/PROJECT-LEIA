"""Phase C: settings store, business-hours pacing, and the gated scheduler tick."""

from __future__ import annotations

from datetime import datetime

from leia.config import load_icp
from leia.models import ConversationThread, Prospect, ScoredLead, ThreadStatus
from leia.pacing import UK, within_business_hours
from leia.pipeline import ensure_icp_row
from leia.tick import run_scheduler_tick
from leia.web.settings_store import get_runtime_settings, save_runtime_settings

# ── Settings store ──────────────────────────────────────────────────────────


def test_settings_defaults_match_storyboard(session):
    s = get_runtime_settings(session)
    assert s["always_ask"] is True  # the core safety rule, on by default
    assert s["daily_send_cap"] == 25
    assert s["default_tone"] == "warm_concise"
    assert s["signal_hiring_funding"] is True
    assert s["signal_contract_renewal"] is False
    assert s["outreach_paused"] is False


def test_settings_round_trip_and_coercion(session):
    out = save_runtime_settings(
        session,
        {"always_ask": "false", "daily_send_cap": "40", "default_tone": "direct"},
    )
    assert out["always_ask"] is False  # "false" string coerced to bool
    assert out["daily_send_cap"] == 40
    assert out["default_tone"] == "direct"
    # persisted
    assert get_runtime_settings(session)["daily_send_cap"] == 40


def test_settings_clamp_and_reject_bad_values(session):
    out = save_runtime_settings(
        session,
        {"daily_send_cap": 99999, "default_tone": "nonsense", "bogus_key": 1},
    )
    assert out["daily_send_cap"] == 1000  # clamped
    assert out["default_tone"] == "warm_concise"  # bad tone falls back to default
    assert "bogus_key" not in out  # unknown keys ignored


# ── Pacing ──────────────────────────────────────────────────────────────────


def test_within_business_hours_weekday_midday():
    assert within_business_hours(datetime(2026, 6, 24, 12, 0, tzinfo=UK)) is True


def test_outside_business_hours_evening():
    assert within_business_hours(datetime(2026, 6, 24, 20, 0, tzinfo=UK)) is False


def test_no_business_hours_on_weekend():
    sat = datetime(2026, 6, 27, 12, 0, tzinfo=UK)
    assert sat.weekday() == 5
    assert within_business_hours(sat) is False


# ── /api/settings endpoints ─────────────────────────────────────────────────


def _client():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from leia.db import make_session_factory
    from leia.models import Base
    from leia.web import server

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    server.configure_factory(make_session_factory(engine))
    return TestClient(server.app)


def test_settings_endpoint_get_and_put():
    client = _client()
    body = client.get("/api/settings").json()
    assert body["settings"]["always_ask"] is True
    assert {"value": "warm_concise", "label": "Warm & concise"} in body["tone_options"]

    put = client.put("/api/settings", json={"settings": {"daily_send_cap": 10}})
    assert put.status_code == 200
    assert put.json()["settings"]["daily_send_cap"] == 10
    assert client.get("/api/settings").json()["settings"]["daily_send_cap"] == 10


# ── The gated tick ──────────────────────────────────────────────────────────


def _seed_scored_linkedin(session, key="p-sched"):
    icp_row = ensure_icp_row(session, load_icp())
    p = Prospect(
        full_name="Maya Rao",
        company_name="Northwind",
        dedupe_key=key,
        linkedin_url="https://www.linkedin.com/in/maya-rao",
    )
    session.add(p)
    session.flush()
    session.add(ScoredLead(prospect_id=p.id, icp_id=icp_row.id, score=90, tier="A"))
    session.commit()
    return p


def test_tick_drafts_openers_by_default(session):
    """Default settings (always_ask on) → the tick prepares openers but sends nothing."""
    _seed_scored_linkedin(session)
    out = run_scheduler_tick(session, dry_run=True, force=True)
    assert out["initiated"]["drafted"] >= 1
    assert out["initiated"]["sent"] == 0
    thread = session.query(ConversationThread).one()
    assert thread.status == ThreadStatus.AWAITING_HUMAN


def test_tick_auto_sends_when_always_ask_off(session):
    _seed_scored_linkedin(session)
    save_runtime_settings(session, {"always_ask": False})
    out = run_scheduler_tick(session, dry_run=True, force=True)
    assert out["initiated"]["sent"] >= 1


def test_tick_kill_switch_blocks_all_sends(session):
    """outreach_paused holds everything, even with always_ask off and force on."""
    _seed_scored_linkedin(session)
    save_runtime_settings(session, {"always_ask": False, "outreach_paused": True})
    out = run_scheduler_tick(session, dry_run=True, force=True)
    assert out["paused"] is True
    assert out["initiated"]["sent"] == 0
    assert out["initiated"]["drafted"] >= 1  # drafted, awaiting human
