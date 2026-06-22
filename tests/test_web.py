"""Offline tests for the web control center.

Uses FastAPI's TestClient against an in-memory SQLite DB (shared via StaticPool)
and dry-run/stub providers — no network, no spend, no real sends.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

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
    assert "PROJECT-LEIA" in r.text


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
