"""Event-window expansion."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def expand_event(event: dict) -> list[dict]:
    """Return the event's fifteen-minute interval starts."""
    zone = ZoneInfo(event["timezone"])
    current = datetime.fromisoformat(event["start_local"]).replace(tzinfo=zone)
    end = datetime.fromisoformat(event["end_local"]).replace(tzinfo=zone)
    intervals = []
    while current < end:
        intervals.append(
            {
                "local_start": current,
                "start_utc": current.astimezone(ZoneInfo("UTC")),
            }
        )
        current = (current.replace(tzinfo=None) + timedelta(minutes=15)).replace(
            tzinfo=zone
        )
    return intervals
