"""Phase D backends: analytics period, Adjust-tone re-draft, conversation surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from leia.db import make_session_factory
from leia.models import (
    Base,
    ConversationThread,
    Message,
    MessageDirection,
    Prospect,
    ThreadStatus,
)
from leia.web import server


def _client_and_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    server.configure_factory(factory)
    return TestClient(server.app), factory


def _run_dry(client):
    return client.post(
        "/api/run",
        json={
            "source": "manual_csv",
            "dry_run": True,
            "input_csv": "data/fixtures/contacts.sample.csv",
        },
    ).json()


# ── Analytics ────────────────────────────────────────────────────────────────


def test_stats_period_shape():
    client, _ = _client_and_factory()
    body = client.get("/api/stats?period=30d").json()
    assert body["period"] == "30d"
    assert set(body["kpis"]) == {"reply_rate", "meetings_booked", "avg_lead_score"}
    assert len(body["pipeline"]) == 5
    assert [p["stage"] for p in body["pipeline"]][0] == "Contacted"
    assert len(body["score_distribution"]) == 5
    assert len(body["labels"]) == 30  # 30 daily buckets
    # KPI carries value + delta + sparkline
    assert set(body["kpis"]["reply_rate"]) >= {"value", "delta", "spark"}


def test_stats_defaults_to_7d():
    client, _ = _client_and_factory()
    body = client.get("/api/stats").json()
    assert body["period"] == "7d"
    assert len(body["labels"]) == 7


def test_stats_distribution_counts_scores():
    client, _ = _client_and_factory()
    _run_dry(client)  # creates scored leads
    dist = client.get("/api/stats?period=90d").json()["score_distribution"]
    assert sum(b["count"] for b in dist) >= 1  # the dry run scored some leads


# ── Adjust-tone re-draft ──────────────────────────────────────────────────────


def test_retone_rewrites_a_pending_draft():
    client, _ = _client_and_factory()
    _run_dry(client)
    approval_id = client.get("/api/approvals").json()[0]["id"]
    r = client.post(f"/api/approvals/{approval_id}/retone", json={"adjustment": "shorter"})
    assert r.status_code == 200
    assert r.json()["body"]  # a regenerated body comes back


def test_retone_rejects_unknown_adjustment():
    client, _ = _client_and_factory()
    _run_dry(client)
    approval_id = client.get("/api/approvals").json()[0]["id"]
    r = client.post(f"/api/approvals/{approval_id}/retone", json={"adjustment": "spicy"})
    assert r.status_code == 422


# ── Conversations surface ─────────────────────────────────────────────────────


def _seed_awaiting_thread(factory, *, with_inbound=True):
    with factory() as s:
        p = Prospect(
            full_name="Aline Akpovi", company_name="Caudalie", dedupe_key="aline",
            linkedin_url="https://www.linkedin.com/in/aline",
        )
        s.add(p)
        s.flush()
        t = ConversationThread(
            prospect_id=p.id, channel="linkedin", status=ThreadStatus.AWAITING_HUMAN
        )
        s.add(t)
        s.flush()
        if with_inbound:
            s.add(Message(
                thread_id=t.id, direction=MessageDirection.INBOUND,
                body="Sounds interesting — can we talk next week?",
            ))
        s.add(Message(
            thread_id=t.id, direction=MessageDirection.OUTBOUND,
            body="Happy to — here's my booking link.", provider_id=None,
        ))
        s.commit()
        return t.id


def test_conversations_lists_awaiting_human():
    client, factory = _client_and_factory()
    _seed_awaiting_thread(factory)
    rows = client.get("/api/conversations?status=awaiting_human").json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Aline Akpovi"
    assert rows[0]["their_message"]
    assert rows[0]["draft_reply"]
    assert rows[0]["is_opener"] is False


def test_conversation_send_marks_message_sent():
    client, factory = _client_and_factory()
    tid = _seed_awaiting_thread(factory)
    r = client.post(f"/api/conversations/{tid}/send", json={})
    assert r.status_code == 200
    # The pending outbound message now has a provider id (sent), thread back to active.
    with factory() as s:
        msgs = s.query(Message).filter(Message.thread_id == tid).all()
        out = [m for m in msgs if m.direction == MessageDirection.OUTBOUND]
        assert out and out[0].provider_id is not None


def test_conversation_mark_booked():
    client, factory = _client_and_factory()
    tid = _seed_awaiting_thread(factory)
    r = client.post(f"/api/conversations/{tid}/mark-booked")
    assert r.status_code == 200
    assert r.json()["status"] == ThreadStatus.BOOKED
