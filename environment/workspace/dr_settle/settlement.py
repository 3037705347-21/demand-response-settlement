"""Settlement calculations."""

from __future__ import annotations

from .baseline import baseline_for_intervals
from .calendar import expand_event


def settle(events: list[dict], readings: list[dict], baseline_days: list[dict]) -> dict:
    """Build the settlement payload."""
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
        for interval, baseline_kw in zip(intervals, baselines, strict=True):
            actual_kw = reading_by_key[(event["site_id"], interval["start_utc"])]
            reduction_kw = baseline_kw - actual_kw
            payment_usd = reduction_kw * 0.25 * event["rate_usd_per_kwh"]
            rows.append(
                {
                    "local_start": interval["local_start"].isoformat(),
                    "start_utc": interval["start_utc"]
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "baseline_kw": round(baseline_kw, 3),
                    "actual_kw": round(actual_kw, 3),
                    "reduction_kw": round(reduction_kw, 3),
                    "eligible_reduction_kw": round(reduction_kw, 3),
                    "payment_usd": round(payment_usd, 3),
                }
            )
        output_events.append(
            {
                "event_id": event["event_id"],
                "site_id": event["site_id"],
                "timezone": event["timezone"],
                "committed_kw": round(event["committed_kw"], 3),
                "rate_usd_per_kwh": round(event["rate_usd_per_kwh"], 3),
                "intervals": rows,
                "totals": {
                    "reduction_kwh": round(
                        sum(row["reduction_kw"] for row in rows) * 0.25, 3
                    ),
                    "eligible_kwh": round(
                        sum(row["eligible_reduction_kw"] for row in rows) * 0.25, 3
                    ),
                    "payment_usd": round(
                        sum(row["payment_usd"] for row in rows), 3
                    ),
                },
            }
        )
    return {"currency": "USD", "events": output_events}
