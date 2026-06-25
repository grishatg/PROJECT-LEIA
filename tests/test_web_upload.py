"""Offline tests for the CSV upload endpoint (browser-text -> validated server file)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from leia.db import make_session_factory
from leia.models import Base
from leia.web import server


def _client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    server.configure_factory(make_session_factory(engine))
    return TestClient(server.app)


_GOOD = "full_name,company_name,email\nJane Carter,Northwind,jane@northwind.com\nBob Lee,Acme,\n"


def test_upload_valid_csv_returns_path_and_row_count():
    r = _client().post("/api/upload", json={"filename": "my leads!.csv", "content": _GOOD})
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == 2
    assert body["path"].endswith(".csv")
    # filename is sanitised
    assert " " not in body["filename"] and "!" not in body["filename"]
    # the file was actually written and is readable
    from pathlib import Path

    assert Path(body["path"]).read_text().startswith("full_name")


def test_upload_rejects_missing_name_column():
    no_name = "company,email\nAcme,a@b.c\n"
    r = _client().post("/api/upload", json={"filename": "x.csv", "content": no_name})
    assert r.status_code == 400
    assert "name column" in r.json()["detail"].lower()


def test_upload_rejects_empty_file():
    r = _client().post("/api/upload", json={"filename": "x.csv", "content": "   "})
    assert r.status_code == 400
