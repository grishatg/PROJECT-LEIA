"""Analytics for the dashboard: KPIs, trends, pipeline, score distribution.

Pulls the rows once and buckets in Python — the dataset is small for a solo user, and
this keeps the queries simple + portable across SQLite/Postgres. Everything is computed
over a rolling window (7/30/90 days) with a "vs previous period" delta on each KPI.

Returned shape is a superset of the old ``{labels, drafted, sent}`` so the existing chart
keeps working while the new Analytics screen reads the richer keys.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from leia.models import (
    ConversationThread,
    DraftMessage,
    Meeting,
    MeetingStatus,
    Message,
    MessageDirection,
    OutreachEvent,
    OutreachLog,
    ScoredLead,
    ThreadStatus,
)

PERIODS = {"7d": 7, "30d": 30, "90d": 90}

_SCORE_BANDS = [
    ("<40", 0, 40),
    ("40–55", 40, 55),
    ("55–70", 55, 70),
    ("70–85", 70, 85),
    ("85–100", 85, 101),
]


def _day_keys(end_date, days: int) -> list:
    return [end_date - timedelta(days=i) for i in range(days - 1, -1, -1)]


def _label(d, days: int) -> str:
    # Weekday for a week, "D Mon" for longer ranges (keeps the axis readable).
    return d.strftime("%a") if days <= 7 else d.strftime("%-d %b")


def _bucket(rows, days_window) -> dict:
    out = {d: 0 for d in days_window}
    for dt in rows:
        if dt and dt.date() in out:
            out[dt.date()] += 1
    return out


def _reply_rate(sent: int, replies: int) -> int:
    return round(100 * replies / sent) if sent else 0


def compute_analytics(session: Session, period: str = "7d", account_id: str = "local") -> dict:
    days = PERIODS.get(period, 7)
    today = datetime.now(UTC).date()
    window = _day_keys(today, days)
    prev_window = _day_keys(today - timedelta(days=days), days)
    win_start = window[0]
    prev_start = prev_window[0]

    # ── Pull the rows we need once ───────────────────────────────────────────
    draft_dates = [c for (c,) in session.execute(select(DraftMessage.created_at))]
    sent_logs = [
        occurred
        for (occurred, event) in session.execute(
            select(OutreachLog.occurred_at, OutreachLog.event)
        )
        if event == OutreachEvent.SENT
    ]
    msgs = session.execute(
        select(Message.direction, Message.occurred_at, Message.provider_id)
    ).all()
    out_sent = [o for (d, o, pid) in msgs if d == MessageDirection.OUTBOUND and pid]
    inbound = [o for (d, o, pid) in msgs if d == MessageDirection.INBOUND]
    scores = session.execute(select(ScoredLead.score, ScoredLead.created_at)).all()
    meetings = session.execute(
        select(Meeting.status, Meeting.created_at, Meeting.booked_at)
    ).all()

    # Outreach over time = sends per day (provider sends + conversation sends).
    sent_per_day = _bucket(sent_logs, window)
    for o in out_sent:
        if o and o.date() in sent_per_day:
            sent_per_day[o.date()] += 1
    drafted_per_day = _bucket(draft_dates, window)
    inbound_per_day = _bucket(inbound, window)

    labels = [_label(d, days) for d in window]
    sent_series = [sent_per_day[d] for d in window]
    drafted_series = [drafted_per_day[d] for d in window]

    # ── KPI: reply rate ──────────────────────────────────────────────────────
    def _count_in(rows, start):
        return sum(1 for r in rows if r and start <= r.date() <= today)

    sent_now = sum(sent_series)
    replies_now = sum(inbound_per_day[d] for d in window)
    sent_prev = _count_in(sent_logs, prev_start) + _count_in(out_sent, prev_start)
    # (prev replies are bounded to the prior window)
    replies_prev = sum(1 for o in inbound if o and prev_start <= o.date() < win_start)
    reply_rate_now = _reply_rate(sent_now, replies_now)
    reply_rate_prev = _reply_rate(sent_prev, replies_prev)
    reply_spark = [
        _reply_rate(sent_per_day[d], inbound_per_day[d]) for d in window
    ]

    # ── KPI: meetings booked ─────────────────────────────────────────────────
    booked_dates = [
        (b or c) for (st, c, b) in meetings if st == MeetingStatus.BOOKED
    ]
    booked_per_day = _bucket(booked_dates, window)
    meetings_now = sum(booked_per_day[d] for d in window)
    meetings_prev = sum(1 for d in booked_dates if d and prev_start <= d.date() < win_start)

    # ── KPI: average lead score ──────────────────────────────────────────────
    def _avg_scores(start, end):
        vals = [s for (s, c) in scores if c and start <= c.date() <= end]
        return round(sum(vals) / len(vals)) if vals else 0

    avg_score_now = _avg_scores(win_start, today)
    avg_score_prev = _avg_scores(prev_start, win_start - timedelta(days=1))
    score_by_day = {d: [] for d in window}
    for s, c in scores:
        if c and c.date() in score_by_day:
            score_by_day[c.date()].append(s)
    score_spark = [
        round(sum(v) / len(v)) if v else 0 for v in (score_by_day[d] for d in window)
    ]

    # ── Pipeline by stage ────────────────────────────────────────────────────
    threads = session.execute(
        select(ConversationThread.id, ConversationThread.status)
    ).all()
    thread_ids_with_inbound = {
        tid for (tid,) in session.execute(
            select(Message.thread_id).where(Message.direction == MessageDirection.INBOUND)
        )
    }
    contacted = len(threads)
    replied = sum(1 for (tid, _st) in threads if tid in thread_ids_with_inbound)
    proposal = sum(1 for (_id, st) in threads if st == ThreadStatus.MEETING_LINK_SHARED)
    won = sum(1 for (st, _c, _b) in meetings if st == MeetingStatus.BOOKED)
    meeting_stage = sum(
        1 for (st, _c, _b) in meetings
        if st in (MeetingStatus.LINK_SHARED, MeetingStatus.BOOKED)
    )
    pipeline = [
        {"stage": "Contacted", "count": contacted},
        {"stage": "Replied", "count": replied},
        {"stage": "Meeting booked", "count": meeting_stage},
        {"stage": "Proposal", "count": proposal},
        {"stage": "Won", "count": won},
    ]

    # ── Score distribution ───────────────────────────────────────────────────
    all_scores = [s for (s, _c) in scores]
    distribution = [
        {"band": band, "count": sum(1 for s in all_scores if lo <= s < hi)}
        for (band, lo, hi) in _SCORE_BANDS
    ]

    return {
        "period": period if period in PERIODS else "7d",
        "labels": labels,
        "drafted": drafted_series,
        "sent": sent_series,
        "kpis": {
            "reply_rate": {
                "value": reply_rate_now,
                "delta": reply_rate_now - reply_rate_prev,
                "spark": reply_spark,
                "suffix": "%",
            },
            "meetings_booked": {
                "value": meetings_now,
                "delta": meetings_now - meetings_prev,
                "spark": [booked_per_day[d] for d in window],
                "suffix": "",
            },
            "avg_lead_score": {
                "value": avg_score_now,
                "delta": avg_score_now - avg_score_prev,
                "spark": score_spark,
                "suffix": "",
            },
        },
        "reply_rate_trend": {"labels": labels, "values": reply_spark},
        "pipeline": pipeline,
        "score_distribution": distribution,
    }
