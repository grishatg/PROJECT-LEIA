"""FastAPI control center for PROJECT-LEIA.

A thin, local-only web layer over the existing pipeline functions. Every endpoint
reuses code from leia.pipeline / leia.approval.queue / leia.config and talks to the
same database. The human-approval gate is unchanged: nothing is sent unless a draft
has been APPROVED here first.

Launch with ``leia dashboard`` (binds to 127.0.0.1 — not exposed to the network).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from leia.approval.queue import approve, list_pending, reject
from leia.config import (
    ICPConfig,
    get_settings,
    load_app_settings,
    load_icp,
    load_message_guidelines,
    load_value_prop,
)
from leia.db import make_engine, make_session_factory, session_scope
from leia.models import (
    ApprovalItem,
    ApprovalState,
    DraftMessage,
    DraftStatus,
    EnrichedContact,
    OutreachEvent,
    OutreachLog,
    Prospect,
    ScoredLead,
)
from leia.pipeline import build_components, run_until_queue, send_approved
from leia.web.serializers import serialize_approval, serialize_outreach

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_ICP_PATH = _REPO_ROOT / "config" / "icp.yaml"

templates = Jinja2Templates(directory=str(_HERE / "templates"))

app = FastAPI(title="PROJECT-LEIA", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

# One engine/session-factory per process. Tests override this via configure_factory().
_session_factory = make_session_factory(make_engine())


def configure_factory(factory) -> None:
    """Point the app at a specific session factory (used by tests)."""
    global _session_factory
    _session_factory = factory


def get_session() -> Iterator[Session]:
    with session_scope(_session_factory) as session:
        yield session


# ── Page ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


# ── Status / stats ────────────────────────────────────────────────────────────


@app.get("/api/status")
def status(session: Session = Depends(get_session)) -> dict:
    s = get_settings()

    def _count(stmt) -> int:
        return session.execute(stmt).scalar_one() or 0

    prospects = _count(select(func.count()).select_from(Prospect))
    enriched = _count(select(func.count()).select_from(EnrichedContact))
    pending = _count(
        select(func.count()).select_from(ApprovalItem).where(
            ApprovalItem.state == ApprovalState.PENDING
        )
    )
    approved = _count(
        select(func.count()).select_from(DraftMessage).where(
            DraftMessage.status == DraftStatus.APPROVED
        )
    )
    sent = _count(
        select(func.count()).select_from(DraftMessage).where(
            DraftMessage.status == DraftStatus.SENT
        )
    )
    score_cost = session.execute(
        select(func.coalesce(func.sum(ScoredLead.cost_usd), 0.0))
    ).scalar_one()
    draft_cost = session.execute(
        select(func.coalesce(func.sum(DraftMessage.cost_usd), 0.0))
    ).scalar_one()

    return {
        "tiles": {
            "prospects": prospects,
            "enriched": enriched,
            "queued": pending,
            "approved": approved,
            "sent": sent,
            "spend_usd": round(float(score_cost) + float(draft_cost), 4),
        },
        # Placeholders for engagement metrics that need a provider stats sync.
        "coming_soon": ["delivered", "opened", "replied"],
        "keys": {
            "anthropic": bool(s.anthropic_api_key),
            "lusha": bool(s.lusha_api_key),
            "instantly": bool(s.instantly_api_key and s.instantly_campaign_id),
            "apify": bool(s.apify_token),
            "unipile": bool(s.unipile_api_key and s.unipile_dsn),
        },
    }


@app.get("/api/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    """Daily counts for the last 7 days: drafts created and messages sent."""
    today = datetime.now(UTC).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    labels = [d.strftime("%a") for d in days]
    drafted = {d: 0 for d in days}
    sent = {d: 0 for d in days}

    for (created,) in session.execute(select(DraftMessage.created_at)):
        if created and created.date() in drafted:
            drafted[created.date()] += 1
    for (occurred, event) in session.execute(
        select(OutreachLog.occurred_at, OutreachLog.event)
    ):
        if occurred and event == OutreachEvent.SENT and occurred.date() in sent:
            sent[occurred.date()] += 1

    return {
        "labels": labels,
        "drafted": [drafted[d] for d in days],
        "sent": [sent[d] for d in days],
    }


# ── Approvals ─────────────────────────────────────────────────────────────────


@app.get("/api/approvals")
def approvals(session: Session = Depends(get_session)) -> list[dict]:
    return [serialize_approval(session, item) for item in list_pending(session)]


@app.post("/api/approvals/{approval_id}/approve")
def approve_one(
    approval_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
) -> dict:
    try:
        item = approve(
            session,
            approval_id,
            note=payload.get("note") or None,
            edited_subject=payload.get("edited_subject"),
            edited_body=payload.get("edited_body"),
        )
    except Exception as e:  # noqa: BLE001 - surface a clean 404/400 to the UI
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"id": item.id, "state": item.state}


@app.post("/api/approvals/{approval_id}/reject")
def reject_one(
    approval_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
) -> dict:
    try:
        item = reject(session, approval_id, note=payload.get("note") or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"id": item.id, "state": item.state}


# ── Run / Send ────────────────────────────────────────────────────────────────


def _build_source(source: str, *, dry_run: bool, input_csv: str | None, dataset: str | None,
                  icp: ICPConfig, app_settings, settings):
    """Construct a SignalSource from request params (mirrors the CLI logic)."""
    if source == "manual_csv":
        from leia.sources.manual_csv import ManualCSVSource

        if not input_csv:
            raise HTTPException(400, "input_csv is required for manual_csv")
        return ManualCSVSource(input_csv)

    if source == "apify_linkedin":
        if not dataset:
            raise HTTPException(400, "dataset is required for apify_linkedin")
        if not settings.apify_token:
            raise HTTPException(400, "APIFY_TOKEN is not set in .env")
        from leia.sources.apify_linkedin import ApifyLinkedInSource

        return ApifyLinkedInSource(settings.apify_token, dataset)

    if source == "lusha_prospecting":
        if dry_run:
            from leia.sources.lusha_stub import StubLushaProspectingSource

            return StubLushaProspectingSource()
        if not settings.lusha_api_key:
            raise HTTPException(400, "LUSHA_API_KEY is required for lusha_prospecting")
        from leia.sources.lusha import LushaProspectingSource

        return LushaProspectingSource(
            settings.lusha_api_key, icp, max_results=app_settings.lusha.max_prospects
        )

    if source == "lusha_signals":
        if dry_run:
            from leia.sources.lusha_stub import StubLushaSignalsSource

            return StubLushaSignalsSource(signal_types=app_settings.lusha.signal_types)
        if not settings.lusha_api_key:
            raise HTTPException(400, "LUSHA_API_KEY is required for lusha_signals")
        from leia.sources.lusha import LushaSignalsSource

        return LushaSignalsSource(
            settings.lusha_api_key,
            icp,
            days_back=app_settings.lusha.signals_days_back,
            signal_types=app_settings.lusha.signal_types,
            max_results=app_settings.lusha.max_prospects,
        )

    raise HTTPException(400, f"Unknown source '{source}'")


@app.post("/api/run")
def run_pipeline(
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
) -> dict:
    source = payload.get("source", "manual_csv")
    dry_run = bool(payload.get("dry_run", True))
    limit = payload.get("limit")
    input_csv = payload.get("input_csv")
    dataset = payload.get("dataset")

    settings = get_settings()
    app_settings = load_app_settings()
    icp = load_icp()
    vp = load_value_prop()
    guidelines = load_message_guidelines()

    if limit and source in ("lusha_prospecting", "lusha_signals"):
        app_settings.lusha.max_prospects = min(app_settings.lusha.max_prospects, int(limit))

    signal_source = _build_source(
        source, dry_run=dry_run, input_csv=input_csv, dataset=dataset,
        icp=icp, app_settings=app_settings, settings=settings,
    )

    try:
        components = build_components(dry_run=dry_run, settings=settings, app_settings=app_settings)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    reports = run_until_queue(
        session,
        source=signal_source,
        components=components,
        icp_config=icp,
        value_prop=vp,
        guidelines=guidelines,
        limit=int(limit) if limit else None,
    )
    reports["notes"] = components.notes
    return reports


@app.post("/api/send")
def send(
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
) -> dict:
    dry_run = bool(payload.get("dry_run", True))
    settings = get_settings()
    app_settings = load_app_settings()
    components = build_components(
        dry_run=dry_run, settings=settings, app_settings=app_settings, require_brain=False
    )
    report = send_approved(
        session, components.channel_for, daily_cap=app_settings.limits.daily_send_cap
    )
    return {"counts": report.counts, "notes": components.notes, "dry_run": dry_run}


@app.get("/api/history")
def history(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(OutreachLog).order_by(OutreachLog.occurred_at.desc()).limit(50)
    ).scalars().all()
    return [serialize_outreach(session, r) for r in rows]


# ── Settings (ICP) ────────────────────────────────────────────────────────────


@app.get("/api/config/icp")
def get_icp() -> dict:
    return load_icp(_ICP_PATH).model_dump()


@app.put("/api/config/icp")
def put_icp(payload: dict = Body(...)) -> dict:
    try:
        cfg = ICPConfig.model_validate(payload)
    except Exception as e:  # noqa: BLE001 - validation message back to the UI
        raise HTTPException(422, f"Invalid ICP: {e}") from e
    _ICP_PATH.write_text(
        yaml.safe_dump(cfg.model_dump(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return cfg.model_dump()
