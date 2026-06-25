"""Offline tests for the web control center.

Uses FastAPI's TestClient against an in-memory SQLite DB (shared via StaticPool)
and dry-run/stub providers — no network, no spend, no real sends.
"""

from __future__ import annotations

import time

import jwt
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from leia.config import get_settings
from leia.db import make_session_factory
from leia.models import Base
from leia.web import server


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    server.configure_factory(make_session_factory(engine))
    return TestClient(server.app)


def _run_dry(client: TestClient) -> dict:
    return client.post(
        "/api/run",
        json={
            "source": "manual_csv",
            "dry_run": True,
            "input_csv": "data/fixtures/contacts.sample.csv",
        },
    ).json()


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "LEIA" in r.text


def test_status_starts_empty(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["tiles"]["queued"] == 0
    assert set(body["keys"]) == {"anthropic", "lusha", "instantly", "apify", "unipile"}
    assert "delivered" in body["coming_soon"]


def test_run_dry_run_queues_drafts(client):
    reports = _run_dry(client)
    assert reports["ingest"]["prospects"] == 5
    assert reports["enqueue"]["queued"] == 8  # 4 fits x email+linkedin (both stubbed in dry-run)

    approvals = client.get("/api/approvals").json()
    assert len(approvals) == 8
    card = approvals[0]
    assert card["full_name"]
    assert card["body"]
    assert card["initials"]


def test_status_reflects_run(client):
    _run_dry(client)
    tiles = client.get("/api/status").json()["tiles"]
    assert tiles["prospects"] == 5
    assert tiles["queued"] == 8


def test_approve_then_send_dry(client):
    _run_dry(client)
    approvals = client.get("/api/approvals").json()
    first = approvals[0]["id"]

    r = client.post(f"/api/approvals/{first}/approve", json={"note": "looks good"})
    assert r.status_code == 200
    assert r.json()["state"] == "approved"

    # one fewer pending now
    assert len(client.get("/api/approvals").json()) == 7

    sent = client.post("/api/send", json={"dry_run": True}).json()
    assert sent["counts"]["sent"] == 1
    assert sent["dry_run"] is True


def test_reject_removes_from_queue(client):
    _run_dry(client)
    approvals = client.get("/api/approvals").json()
    rid = approvals[0]["id"]
    assert client.post(f"/api/approvals/{rid}/reject", json={}).json()["state"] == "rejected"
    assert len(client.get("/api/approvals").json()) == 7


def test_approve_with_edited_body(client):
    _run_dry(client)
    card = client.get("/api/approvals").json()[0]
    client.post(
        f"/api/approvals/{card['id']}/approve",
        json={"edited_body": "Custom hand-edited body."},
    )
    # the edit flows through to send (stub) without error
    sent = client.post("/api/send", json={"dry_run": True}).json()
    assert sent["counts"]["sent"] == 1


def test_export_prospects_csv(client):
    _run_dry(client)
    r = client.get("/api/export/prospects.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("full_name,company_name,title,email,email_status")
    assert len(lines) == 6  # header + 5 sample prospects


def test_prospects_list_after_run(client):
    _run_dry(client)
    rows = client.get("/api/prospects").json()
    assert len(rows) == 5  # all 5 sample prospects appear
    assert all("score" in r and "initials" in r and "status" in r for r in rows)
    scored = [r for r in rows if r["score"] is not None]
    assert scored == sorted(scored, key=lambda r: r["score"], reverse=True)  # best first


def test_rescore_updates_scores_in_place(client):
    _run_dry(client)
    before = client.get("/api/prospects").json()
    n_scored = len([r for r in before if r["score"] is not None])

    r = client.post("/api/rescore", json={"dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["counts"]["scored"] == n_scored

    after = client.get("/api/prospects").json()
    assert len(after) == len(before)  # no new prospects, just re-scored


def test_prospect_detail(client):
    _run_dry(client)
    pid = client.get("/api/prospects").json()[0]["id"]
    detail = client.get(f"/api/prospects/{pid}").json()
    assert detail["full_name"]
    assert "outreach" in detail and "pending" in detail and "matched_criteria" in detail
    assert client.get("/api/prospects/does-not-exist").status_code == 404


def test_stats_shape(client):
    _run_dry(client)
    stats = client.get("/api/stats").json()
    assert len(stats["labels"]) == 7
    assert sum(stats["drafted"]) == 8  # email+linkedin drafts created today


def test_icp_config_roundtrip(client, tmp_path, monkeypatch):
    icp_file = tmp_path / "icp.yaml"
    original = client.get("/api/config/icp").json()
    icp_file.write_text(yaml.safe_dump(original), encoding="utf-8")
    monkeypatch.setattr(server, "_ICP_PATH", icp_file)

    payload = dict(original)
    payload["score_threshold"] = 42
    payload["name"] = "Edited ICP"
    saved = client.put("/api/config/icp", json=payload).json()
    assert saved["score_threshold"] == 42

    reloaded = yaml.safe_load(icp_file.read_text())
    assert reloaded["score_threshold"] == 42
    assert reloaded["name"] == "Edited ICP"


def test_icp_rejects_bad_threshold(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_ICP_PATH", tmp_path / "icp.yaml")
    bad = {"name": "X", "score_threshold": 999}
    assert client.put("/api/config/icp", json=bad).status_code == 422


def test_icp_edit_persists_in_db(client, tmp_path, monkeypatch):
    icp = client.get("/api/config/icp").json()  # read the bundled default first
    # Now point the file at a throwaway path so we don't touch the repo's icp.yaml.
    monkeypatch.setattr(server, "_ICP_PATH", tmp_path / "icp.yaml")
    icp["score_threshold"] = 77
    client.put("/api/config/icp", json=icp)
    # A fresh GET reads back the DB-stored override, not the file.
    assert client.get("/api/config/icp").json()["score_threshold"] == 77


# ── Auth (Supabase JWT) ─────────────────────────────────────────────────────


@pytest.fixture()
def auth_secret(monkeypatch):
    """Enable auth for a test, then reset the settings cache so other tests are free."""
    secret = "test-jwt-secret-please-ignore-0123456789abcdef"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    get_settings.cache_clear()
    yield secret
    get_settings.cache_clear()


def _token(secret: str) -> str:
    return jwt.encode(
        {
            "sub": "user-1",
            "email": "me@example.com",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        secret,
        algorithm="HS256",
    )


def test_public_config_reports_auth_disabled_by_default(client):
    assert client.get("/api/public-config").json()["auth_enabled"] is False


def test_healthz_is_public(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_api_requires_auth_when_configured(client, auth_secret):
    # No token -> 401
    assert client.get("/api/status").status_code == 401
    # Garbage token -> 401
    bad = client.get("/api/status", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    # Valid Supabase-style token -> 200
    ok = client.get(
        "/api/status", headers={"Authorization": f"Bearer {_token(auth_secret)}"}
    )
    assert ok.status_code == 200
