"""Baseline selection."""

from __future__ import annotations

from collections import defaultdict
from zoneinfo import ZoneInfo


def baseline_for_intervals(
    intervals: list[dict],
    readings: list[dict],
    baseline_days: list[dict],
    event_date: str,
    timezone: str,
    site_id: str,
) -> list[float]:
    """Return one baseline average for each event interval."""
    zone = ZoneInfo(timezone)
    known_dates = {day["date"] for day in baseline_days}
    by_clock = defaultdict(list)
    for reading in readings:
        if reading["site_id"] != site_id:
            continue
        local = reading["timestamp_utc"].astimezone(zone)
        if local.date().isoformat() in known_dates:
            by_clock[local.strftime("%H:%M")].append(reading["kw"])
    return [
        sum(by_clock[item["local_start"].strftime("%H:%M")])
        / len(by_clock[item["local_start"].strftime("%H:%M")])
        for item in intervals
    ]
