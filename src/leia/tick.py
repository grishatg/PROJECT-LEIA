"""The scheduler tick: initiate new conversations + advance existing ones, with pacing.

Shared by the web endpoint (``POST /api/tasks/tick``) and the ``leia tick`` CLI that the
Render cron runs. Kept free of FastAPI so the cron can run it directly in-container — no
HTTP, no auth dance. All the gates live here in one place:

- **kill switch** (``outreach_paused``): when on, nothing is sent — replies are still read.
- **business hours**: first-touch + auto-sends only go out in UK working hours (``force``
  overrides, for a manual "run now").
- **daily cap**: enforced across ticks by counting what we've already sent today.
- **always ask** (default on): holds first-touch openers for approval instead of sending.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from leia.config import (
    get_settings,
    load_app_settings,
    load_message_guidelines,
    load_value_prop,
)
from leia.conversation import advance_conversations, initiate_conversations
from leia.inbox.stub import StubInbox
from leia.models import Message, MessageDirection
from leia.pacing import within_business_hours
from leia.pipeline import build_components, ensure_icp_row
from leia.web.config_store import get_effective_icp
from leia.web.settings_store import get_runtime_settings


def sent_today(session: Session, account_id: str = "local") -> int:
    """Conversation messages actually sent today (for the cross-tick daily cap)."""
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.query(Message)
        .filter(
            Message.account_id == account_id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.provider_id.isnot(None),
            Message.occurred_at >= start,
        )
        .count()
    )


def run_scheduler_tick(
    session: Session, *, dry_run: bool = False, force: bool = False
) -> dict:
    """One heartbeat: initiate new LinkedIn conversations, then advance existing ones."""
    settings = get_settings()
    app_settings = load_app_settings()
    rt = get_runtime_settings(session)
    components = build_components(
        dry_run=dry_run, settings=settings, app_settings=app_settings
    )
    if components.brain is None:
        raise RuntimeError("A brain is required to advance conversations.")

    # Read every configured channel's replies in one pass (LinkedIn + email).
    inbox = StubInbox()
    if not dry_run:
        boxes = []
        if settings.unipile_api_key and settings.unipile_dsn:
            from leia.inbox.unipile import UnipileInbox

            boxes.append(
                UnipileInbox(
                    settings.unipile_api_key, settings.unipile_dsn, settings.unipile_account_id
                )
            )
        if settings.instantly_api_key:
            from leia.inbox.instantly import InstantlyInbox

            boxes.append(InstantlyInbox(settings.instantly_api_key))
        if boxes:
            from leia.inbox.multi import MultiInbox

            inbox = MultiInbox(boxes)

    paused = bool(rt["outreach_paused"])
    open_hours = force or within_business_hours()
    daily_cap = int(rt["daily_send_cap"])
    already = sent_today(session)
    budget = max(0, daily_cap - already)
    can_send = (not paused) and open_hours and budget > 0

    icp = get_effective_icp(session)
    icp_row = ensure_icp_row(session, icp)
    vp, guidelines = load_value_prop(), load_message_guidelines()

    initiated = initiate_conversations(
        session,
        brain=components.brain,
        channel_for=components.channel_for,
        value_prop=vp,
        guidelines=guidelines,
        icp_id=icp_row.id,
        channel="linkedin",
        score_threshold=icp.score_threshold,
        auto_send=can_send and not bool(rt["always_ask"]),
        send_cap=budget,
        limit=daily_cap,
    )

    reply_cap = 0 if (paused or not open_hours) else max(0, budget - initiated.get("sent", 0))
    counts = advance_conversations(
        session,
        inbox=inbox,
        brain=components.brain,
        channel_for=components.channel_for,
        value_prop=vp,
        guidelines=guidelines,
        booking_url=settings.booking_url,
        reply_cap=reply_cap,
    )
    return {
        "counts": counts,
        "initiated": initiated,
        "paused": paused,
        "business_hours": open_hours,
        "sent_today": already,
        "notes": components.notes,
    }
