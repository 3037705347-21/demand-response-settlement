"""Recompute the shipped settlement without importing the candidate package."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


TASK = Path(__file__).resolve().parents[1]
DATA = TASK / "environment" / "workspace" / "data"
UTC = ZoneInfo("UTC")


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    event = read_csv("events.csv")[0]
    zone = ZoneInfo(event["timezone"])
    start = datetime.fromisoformat(event["start_local"]).replace(tzinfo=zone, fold=0)
    end = datetime.fromisoformat(event["end_local"]).replace(tzinfo=zone, fold=0)
    cursor = start.astimezone(UTC)
    intervals = []
    while cursor < end.astimezone(UTC):
        intervals.append(cursor.astimezone(zone))
        cursor += timedelta(minutes=15)

    normal = {
        row["date"]
        for row in read_csv("baseline_days.csv")
        if row["status"] == "normal" and row["date"] < event["start_local"][:10]
    }
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    readings = {}
    for row in read_csv("readings.csv"):
        timestamp = datetime.fromisoformat(
            row["timestamp_utc"].replace("Z", "+00:00")
        ).astimezone(UTC)
        kw = float(row["kwh"]) * 4.0
        readings[timestamp] = kw
        local = timestamp.astimezone(zone)
        if local.date().isoformat() in normal:
            by_date[local.date().isoformat()][local.strftime("%H:%M")] = kw
    clocks = {item.strftime("%H:%M") for item in intervals}
    complete = [values for values in by_date.values() if clocks.issubset(values)]
    if len(complete) < 5:
        raise SystemExit("fixture does not have five complete normal days")

    expected_rows = []
    reduction_kw_total = 0.0
    eligible_kw_total = 0.0
    payment_total = 0.0
    for local in intervals:
        clock = local.strftime("%H:%M")
        baseline = sum(sorted(values[clock] for values in complete)[-5:]) / 5.0
        actual = readings[local.astimezone(UTC)]
        reduction = max(0.0, baseline - actual)
        eligible = min(reduction, float(event["committed_kw"]))
        payment = eligible * 0.25 * float(event["rate_usd_per_kwh"])
        reduction_kw_total += reduction
        eligible_kw_total += eligible
        payment_total += payment
        expected_rows.append(
            {
                "local_start": local.isoformat(),
                "baseline_kw": round(baseline, 3),
                "actual_kw": round(actual, 3),
                "reduction_kw": round(reduction, 3),
                "eligible_reduction_kw": round(eligible, 3),
                "payment_usd": round(payment, 3),
            }
        )

    expected = {
        "event_id": event["event_id"],
        "interval_count": len(expected_rows),
        "totals": {
            "reduction_kwh": round(reduction_kw_total * 0.25, 3),
            "eligible_kwh": round(eligible_kw_total * 0.25, 3),
            "payment_usd": round(payment_total, 3),
        },
        "intervals": expected_rows,
    }
    actual = json.loads((TASK / "solution" / "sample-result.json").read_text())
    actual_event = actual["events"][0]
    if actual_event["totals"] != expected["totals"]:
        raise SystemExit(
            f"totals differ: actual {actual_event['totals']} expected {expected['totals']}"
        )
    for actual_row, expected_row in zip(
        actual_event["intervals"], expected_rows, strict=True
    ):
        for key, value in expected_row.items():
            if actual_row[key] != value:
                raise SystemExit(
                    f"{expected_row['local_start']} {key}: "
                    f"actual {actual_row[key]} expected {value}"
                )
    reference_path = TASK / "solution" / "reference-answer.json"
    reference_path.write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(expected["totals"], ensure_ascii=False))
    print(f"verified {len(expected_rows)} intervals")


if __name__ == "__main__":
    main()
