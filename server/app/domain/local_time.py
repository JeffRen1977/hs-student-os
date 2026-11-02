"""Local wall-clock times in a student's IANA timezone (Steps 28–29).

Scheduled planning and reminders are defined in the student's local time ("plan at 04:00",
"remind at 16:00", "quiet 21:00–08:00") but stored and compared as UTC instants. The two
DST edge cases are resolved the same way everywhere:

- a wall time that does not exist (spring forward gap, e.g. 02:30 on the US change day)
  resolves to the instant just after the gap (03:30 local);
- a wall time that happens twice (fall back, e.g. 01:30) resolves to the first one.

Callers that must act once per local day dedupe by local *date*, so the repeated hour can
never produce a second action.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def local_date(instant: datetime, timezone: str) -> date:
    return instant.astimezone(ZoneInfo(timezone)).date()


def at_local(day: date, wall: time, timezone: str) -> datetime:
    """The UTC instant at which `day wall` happens in `timezone` (DST rules above)."""
    zone = ZoneInfo(timezone)
    naive = datetime.combine(day, wall)
    first = naive.replace(tzinfo=zone, fold=0)
    # A non-existent wall time does not round-trip: fold=0 uses the offset from before the
    # gap, which lands after the gap in UTC. That instant is the one we want.
    return first.astimezone(UTC)


def next_at_local(after: datetime, wall: time, timezone: str) -> datetime:
    """The first instant strictly after `after` whose local wall time is `wall`."""
    today = local_date(after, timezone)
    for offset in range(3):
        candidate = at_local(today + timedelta(days=offset), wall, timezone)
        if candidate > after:
            return candidate
    raise AssertionError("unreachable: a wall time recurs within two days")  # pragma: no cover


def in_window(instant: datetime, start: time, end: time, timezone: str) -> bool:
    """Whether the local wall time of `instant` is in [start, end); wraps past midnight."""
    wall = instant.astimezone(ZoneInfo(timezone)).time().replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= wall < end
    return wall >= start or wall < end


def window_end(instant: datetime, start: time, end: time, timezone: str) -> datetime:
    """When the window containing `instant` ends (callers check `in_window` first)."""
    return next_at_local(instant, end, timezone)
