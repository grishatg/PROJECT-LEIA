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
from fastapi.responses import HTMLResponse, Response
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
from leia.web.auth import auth_enabled, require_user
from leia.web.config_store import get_effective_icp, save_icp
from leia.web.serializers import (
    export_prospects_csv,
    serialize_approval,
    serialize_lead_detail,
    serialize_outreach,
    serialize_prospect_row,
)

# Applied to every data route so nothing runs without a verified login (when
# Supabase is configured). Public routes below intentionally omit it.
_AUTH = [Depends(require_user)]

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


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@app.get("/healthz")
def healthz() -> dict:
    """Public health check for the host (Render) — no auth, no DB."""
    return {"ok": True}


@app.get("/api/public-config")
def public_config() -> dict:
    """Non-secret config the browser needs to start a Supabase login."""
    s = get_settings()
    return {
        "auth_enabled": auth_enabled(),
        "supabase_url": s.supabase_url,
        "supabase_anon_key": s.supabase_anon_key,
    }


# ── Status / stats ────────────────────────────────────────────────────────────


@app.get("/api/status", dependencies=_AUTH)
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


@app.get("/api/stats", dependencies=_AUTH)
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


@app.get("/api/approvals", dependencies=_AUTH)
def approvals(session: Session = Depends(get_session)) -> list[dict]:
    return [serialize_approval(session, item) for item in list_pending(session)]


@app.post("/api/approvals/{approval_id}/approve", dependencies=_AUTH)
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


@app.post("/api/approvals/{approval_id}/reject", dependencies=_AUTH)
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

    if source == "companies_house":
        if dry_run:
            from leia.sources.discovery_stub import StubCompaniesHouseSource

            return StubCompaniesHouseSource()
        if not settings.companies_house_api_key:
            raise HTTPException(400, "COMPANIES_HOUSE_API_KEY is required for companies_house")
        from leia.sources.companies_house import CompaniesHouseSource

        ch = app_settings.companies_house
        return CompaniesHouseSource(
            settings.companies_house_api_key,
            sic_codes=ch.sic_codes,
            location=ch.location,
            max_companies=ch.max_companies,
            officers_per_company=ch.officers_per_company,
        )

    if source == "jobspy":
        if dry_run:
            from leia.sources.discovery_stub import StubJobSpySource

            return StubJobSpySource()
        from leia.sources.jobspy import JobSpySource

        js = app_settings.jobspy
        return JobSpySource(
            search_terms=js.search_terms, location=js.location, sites=js.sites, results=js.results
        )

    raise HTTPException(400, f"Unknown source '{source}'")


@app.post("/api/run", dependencies=_AUTH)
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
    icp = get_effective_icp(session)
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


@app.post("/api/send", dependencies=_AUTH)
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


@app.post("/api/tasks/tick", dependencies=_AUTH)
def tasks_tick(
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
) -> dict:
    """Advance conversations: pull the inbox, reply (auto-send `continue`, gate
    meetings, suppress opt-outs). Driven by a scheduler (e.g. a Render cron job).

    Until real inbox providers (Instantly/Unipile) are wired, the inbox is a stub
    — an empty tick is a safe no-op. The hybrid autonomy + suppression logic is
    fully exercised by the offline test suite.
    """
    from leia.conversation import advance_conversations
    from leia.inbox.stub import StubInbox

    settings = get_settings()
    app_settings = load_app_settings()
    try:
        components = build_components(
            dry_run=bool(payload.get("dry_run", False)),
            settings=settings,
            app_settings=app_settings,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    if components.brain is None:
        raise HTTPException(400, "A brain is required to advance conversations.")

    counts = advance_conversations(
        session,
        inbox=StubInbox(),  # TODO: real Instantly/Unipile inbox providers
        brain=components.brain,
        channel_for=components.channel_for,
        value_prop=load_value_prop(),
        guidelines=load_message_guidelines(),
        booking_url=settings.booking_url,
        reply_cap=app_settings.limits.daily_send_cap,
    )
    return {"counts": counts, "notes": components.notes}


@app.get("/api/export/prospects.csv", dependencies=_AUTH)
def export_prospects(session: Session = Depends(get_session)):
    """Download every prospect (+ enrichment, latest score, draft status) as CSV."""
    csv_text = export_prospects_csv(session)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leia-prospects.csv"},
    )


@app.get("/api/prospects", dependencies=_AUTH)
def prospects(session: Session = Depends(get_session)) -> list[dict]:
    """Every prospect (+ enrichment, latest score, signals) for the browse grid."""
    rows = session.execute(
        select(Prospect)
        .where(Prospect.account_id == "local")
        .order_by(Prospect.created_at.desc())
    ).scalars().all()
    out = [serialize_prospect_row(session, p) for p in rows]
    # Highest score first; un-scored prospects sink to the bottom.
    out.sort(key=lambda r: (r["score"] is not None, r["score"] or 0), reverse=True)
    return out


@app.get("/api/prospects/{prospect_id}", dependencies=_AUTH)
def prospect_detail(prospect_id: str, session: Session = Depends(get_session)) -> dict:
    prospect = session.get(Prospect, prospect_id)
    if not prospect:
        raise HTTPException(404, "Prospect not found")
    return serialize_lead_detail(session, prospect)


@app.get("/api/history", dependencies=_AUTH)
def history(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(OutreachLog).order_by(OutreachLog.occurred_at.desc()).limit(50)
    ).scalars().all()
    return [serialize_outreach(session, r) for r in rows]


# ── Settings (ICP) ────────────────────────────────────────────────────────────


@app.get("/api/config/icp", dependencies=_AUTH)
def get_icp(session: Session = Depends(get_session)) -> dict:
    return get_effective_icp(session, str(_ICP_PATH)).model_dump()


@app.put("/api/config/icp", dependencies=_AUTH)
def put_icp(
    payload: dict = Body(...),
    session: Session = Depends(get_session),
) -> dict:
    try:
        cfg = ICPConfig.model_validate(payload)
    except Exception as e:  # noqa: BLE001 - validation message back to the UI
        raise HTTPException(422, f"Invalid ICP: {e}") from e
    # Persist in the DB (survives redeploys); also best-effort write the file for
    # local convenience (ignored on a read-only/ephemeral hosted filesystem).
    save_icp(session, cfg)
    try:
        _ICP_PATH.write_text(
            yaml.safe_dump(cfg.model_dump(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    except OSError:
        pass
    return cfg.model_dump()
