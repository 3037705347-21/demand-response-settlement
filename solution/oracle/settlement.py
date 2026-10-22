"""Demand-response settlement calculations."""

from __future__ import annotations

from .baseline import baseline_for_intervals
from .calendar import expand_event
from .model import InputError


def _rounded(value: float) -> float:
    return round(value + 0.0, 3)


def settle(events: list[dict], readings: list[dict], baseline_days: list[dict]) -> dict:
    """Build the event settlement and its summary fields."""
    reading_by_key = {
        (reading["site_id"], reading["timestamp_utc"]): reading["kw"]
        for reading in readings
    }
    output_events = []
    for event in events:
        intervals = expand_event(event)
        baselines = baseline_for_intervals(
            intervals,
            readings,
            baseline_days,
            event["start_local"][:10],
            event["timezone"],
            event["site_id"],
        )
        rows = []
        reduction_total = 0.0
        eligible_total = 0.0
        payment_total = 0.0
        for interval, baseline_kw in zip(intervals, baselines, strict=True):
            try:
                actual_kw = reading_by_key[
                    (event["site_id"], interval["start_utc"])
                ]
            except KeyError as exc:
                raise InputError(
                    f"missing reading at {interval['start_utc'].isoformat()}"
                ) from exc
            reduction_kw = max(0.0, baseline_kw - actual_kw)
            eligible_kw = min(reduction_kw, event["committed_kw"])
            payment_usd = eligible_kw * 0.25 * event["rate_usd_per_kwh"]
            reduction_total += reduction_kw
            eligible_total += eligible_kw
            payment_total += payment_usd
            rows.append(
                {
                    "local_start": interval["local_start"].isoformat(),
                    "start_utc": interval["start_utc"]
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "baseline_kw": _rounded(baseline_kw),
                    "actual_kw": _rounded(actual_kw),
                    "reduction_kw": _rounded(reduction_kw),
                    "eligible_reduction_kw": _rounded(eligible_kw),
                    "payment_usd": _rounded(payment_usd),
                }
            )
        output_events.append(
            {
                "event_id": event["event_id"],
                "site_id": event["site_id"],
                "timezone": event["timezone"],
                "committed_kw": _rounded(event["committed_kw"]),
                "rate_usd_per_kwh": _rounded(event["rate_usd_per_kwh"]),
                "intervals": rows,
                "totals": {
                    "reduction_kwh": _rounded(reduction_total * 0.25),
                    "eligible_kwh": _rounded(eligible_total * 0.25),
                    "payment_usd": _rounded(payment_total),
                },
            }
        )
    return {"currency": "USD", "events": output_events}
