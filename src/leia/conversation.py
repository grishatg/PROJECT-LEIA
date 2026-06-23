"""The hybrid conversation engine (Phase 2).

For each new inbound reply: match it to a prospect + thread, record it, ask the
brain for the next reply, then apply the **hybrid autonomy + safety** rules:

- ``continue``                  → auto-send (under the per-tick reply cap).
- ``unsubscribe``               → add the address to the suppression list, close
                                  the thread, send nothing.
- ``propose_meeting`` / ``confirm_meeting`` / ``escalate`` / ``negative`` /
  ``out_of_office`` / over cap   → draft the reply but leave it AWAITING_HUMAN
                                  (never auto-sent). Meetings are recorded.

This preserves LEIA's golden rule: nothing that proposes/books a meeting goes out
without a human. Email bodies are cleaned with ``replies.clean_reply`` first.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from leia.channels.base import Channel, OutboundMessage
from leia.config import ValuePropConfig
from leia.dedupe import canonicalize_linkedin_url, normalize_email
from leia.inbox.base import Inbox
from leia.llm.base import Brain
from leia.models import (
    ConversationThread,
    EnrichedContact,
    Meeting,
    MeetingStatus,
    Message,
    MessageDirection,
    Prospect,
    ReplyIntent,
    ThreadStatus,
)
from leia.pipeline import _get_signal_summary, build_facts
from leia.replies.parse import clean_reply
from leia.suppression import add_suppression


def _match_prospect(session: Session, reply, account_id: str) -> Prospect | None:
    """Find the prospect a reply belongs to, by email or LinkedIn URL."""
    if reply.from_email:
        ec = session.execute(
            select(EnrichedContact).where(
                EnrichedContact.account_id == account_id,
                EnrichedContact.email == normalize_email(reply.from_email),
            )
        ).scalar_one_or_none()
        if ec:
            return session.get(Prospect, ec.prospect_id)
    if reply.from_linkedin_url:
        url = canonicalize_linkedin_url(reply.from_linkedin_url)
        return session.execute(
            select(Prospect).where(
                Prospect.account_id == account_id, Prospect.linkedin_url == url
            )
        ).scalar_one_or_none()
    return None


def _get_or_create_thread(
    session: Session, prospect: Prospect, channel: str, account_id: str
) -> ConversationThread:
    thread = session.execute(
        select(ConversationThread).where(
            ConversationThread.account_id == account_id,
            ConversationThread.prospect_id == prospect.id,
            ConversationThread.channel == channel,
        )
    ).scalar_one_or_none()
    if thread is None:
        thread = ConversationThread(
            account_id=account_id, prospect_id=prospect.id, channel=channel,
            status=ThreadStatus.ACTIVE,
        )
        session.add(thread)
        session.flush()
    return thread


def _history(session: Session, thread: ConversationThread) -> list[dict]:
    msgs = session.execute(
        select(Message).where(Message.thread_id == thread.id).order_by(Message.occurred_at)
    ).scalars().all()
    return [{"direction": m.direction, "body": m.body} for m in msgs]


def advance_conversations(
    session: Session,
    *,
    inbox: Inbox,
    brain: Brain,
    channel_for: Callable[[str], Channel],
    value_prop: ValuePropConfig,
    guidelines: str,
    booking_url: str | None = None,
    account_id: str = "local",
    reply_cap: int | None = None,
) -> dict:
    """Process the inbox once and advance every matched conversation."""
    counts = {
        "inbound": 0, "auto_sent": 0, "awaiting_human": 0,
        "suppressed": 0, "unmatched": 0,
    }
    for reply in inbox.fetch_new():
        prospect = _match_prospect(session, reply, account_id)
        if prospect is None:
            counts["unmatched"] += 1
            continue

        thread = _get_or_create_thread(session, prospect, reply.channel, account_id)
        body = clean_reply(reply.body) if reply.channel == "email" else reply.body.strip()
        session.add(
            Message(
                account_id=account_id, thread_id=thread.id,
                direction=MessageDirection.INBOUND, body=body, provider_id=reply.provider_id,
            )
        )
        session.flush()
        counts["inbound"] += 1

        out = brain.converse(
            history=_history(session, thread),
            facts=build_facts(prospect, _get_signal_summary(session, prospect)),
            value_prop=value_prop,
            guidelines=guidelines,
            booking_url=booking_url,
        )
        reply_obj = out.result
        thread.last_intent = reply_obj.intent

        # ── Opt-out: suppress + close, send nothing ──────────────────────────
        if reply_obj.intent == ReplyIntent.UNSUBSCRIBE:
            ec = prospect.enrichment
            add_suppression(
                session, ec.email if ec else None,
                reason="reply opt-out", account_id=account_id,
            )
            thread.status = ThreadStatus.CLOSED
            counts["suppressed"] += 1
            continue

        # ── Auto-send a plain continuation (under the cap) ───────────────────
        can_auto = reply_obj.intent == ReplyIntent.CONTINUE and (
            reply_cap is None or counts["auto_sent"] < reply_cap
        )
        if can_auto:
            ec = prospect.enrichment
            result = channel_for(thread.channel).send(
                OutboundMessage(
                    channel=thread.channel,
                    to_email=ec.email if ec else None,
                    to_linkedin_url=prospect.linkedin_url,
                    body=reply_obj.body,
                )
            )
            session.add(
                Message(
                    account_id=account_id, thread_id=thread.id,
                    direction=MessageDirection.OUTBOUND, body=reply_obj.body,
                    intent=reply_obj.intent, provider_id=result.provider_message_id,
                )
            )
            thread.status = ThreadStatus.ACTIVE
            counts["auto_sent"] += 1
            continue

        # ── Everything else → human gate (drafted, NOT sent) ─────────────────
        session.add(
            Message(
                account_id=account_id, thread_id=thread.id,
                direction=MessageDirection.OUTBOUND, body=reply_obj.body,
                intent=reply_obj.intent, provider_id=None,  # None => drafted, awaiting human
            )
        )
        if reply_obj.intent == ReplyIntent.PROPOSE_MEETING:
            thread.status = ThreadStatus.MEETING_LINK_SHARED
            session.add(
                Meeting(
                    account_id=account_id, prospect_id=prospect.id,
                    thread_id=thread.id, status=MeetingStatus.LINK_SHARED,
                )
            )
        elif reply_obj.intent == ReplyIntent.CONFIRM_MEETING:
            thread.status = ThreadStatus.BOOKED
            session.add(
                Meeting(
                    account_id=account_id, prospect_id=prospect.id,
                    thread_id=thread.id, status=MeetingStatus.BOOKED,
                )
            )
        else:
            thread.status = ThreadStatus.AWAITING_HUMAN
        counts["awaiting_human"] += 1

    session.commit()
    return counts
