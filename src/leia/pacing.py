"""Human-pacing helpers for the scheduler tick.

New conversations only go out during UK business hours so outreach looks human and lands
when people read it. Inbound replies are still processed any time — being slow to reply is
worse than replying at 7pm. Pure + injectable (`now`) so it's testable without the clock.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")


def within_business_hours(
    now: datetime | None = None, *, start_hour: int = 8, end_hour: int = 18
) -> bool:
    """True on a UK weekday between ``start_hour``:00 and ``end_hour``:00."""
    now = now.astimezone(UK) if now is not None else datetime.now(UK)
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    return start_hour <= now.hour < end_hour
