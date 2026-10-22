"""Event-window expansion using elapsed UTC time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc


def _resolve_local(value: datetime, zone: ZoneInfo, *, ending: bool) -> datetime:
    """Resolve an ambiguous or nonexistent local boundary."""
    first = value.replace(tzinfo=zone, fold=0)
    second = value.replace(tzinfo=zone, fold=1)
    first_roundtrip = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    second_roundtrip = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    first_exists = first_roundtrip == value
    second_exists = second_roundtrip == value
    if not first_exists and not second_exists:
        raise ValueError(f"local time does not exist: {value.isoformat()}")
    if first_exists and second_exists and first.utcoffset() != second.utcoffset():
        return second if ending else first
    return first if first_exists else second


def expand_event(event: dict) -> list[dict]:
    """Return fifteen-minute interval starts across any clock transition."""
    zone = ZoneInfo(event["timezone"])
    start = _resolve_local(
        datetime.fromisoformat(event["start_local"]), zone, ending=False
    )
    end = _resolve_local(
        datetime.fromisoformat(event["end_local"]), zone, ending=True
    )
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    intervals = []
    cursor = start_utc
    while cursor < end_utc:
        intervals.append(
            {
                "local_start": cursor.astimezone(zone),
                "start_utc": cursor,
            }
        )
        cursor += timedelta(minutes=15)
    return intervals
