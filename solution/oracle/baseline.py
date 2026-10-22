"""Baseline selection by local wall-clock interval."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .model import InputError


def baseline_for_intervals(
    intervals: list[dict],
    readings: list[dict],
    baseline_days: list[dict],
    event_date: str,
    timezone: str,
    site_id: str,
) -> list[float]:
    """Return the top-five average for each event wall-clock interval."""
    zone = ZoneInfo(timezone)
    normal_dates = {
        day["date"]
        for day in baseline_days
        if day["status"] == "normal" and day["date"] < event_date
    }
    required_clocks = {
        interval["local_start"].strftime("%H:%M") for interval in intervals
    }
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    for reading in readings:
        local = reading["timestamp_utc"].astimezone(zone)
        date_text = local.date().isoformat()
        if reading["site_id"] != site_id or date_text not in normal_dates:
            continue
        clock = local.strftime("%H:%M")
        if clock in by_date[date_text]:
            raise InputError(
                f"baseline day {date_text} repeats the local interval {clock}"
            )
        by_date[date_text][clock] = reading["kw"]
    complete_dates = [
        date_text
        for date_text in sorted(by_date)
        if required_clocks.issubset(by_date[date_text])
    ]
    if len(complete_dates) < 5:
        raise InputError("fewer than five complete normal baseline days")
    baselines = []
    for interval in intervals:
        clock = interval["local_start"].strftime("%H:%M")
        values = sorted(
            (by_date[date_text][clock] for date_text in complete_dates),
            reverse=True,
        )
        baselines.append(sum(values[:5]) / 5.0)
    return baselines
