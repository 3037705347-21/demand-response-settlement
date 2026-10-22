"""Generate the fixed-seed demand-response demonstration tables."""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


SEED = 2417
TIMEZONE = "America/Los_Angeles"
EVENT_DATE = "2026-11-01"
CLOCK_PROFILE = {
    "00:45": 610,
    "01:00": 600,
    "01:15": 590,
    "01:30": 580,
    "01:45": 570,
    "02:00": 540,
}
BASELINE_DAYS = [
    ("2026-10-13", "normal"),
    ("2026-10-14", "normal"),
    ("2026-10-15", "maintenance"),
    ("2026-10-16", "normal"),
    ("2026-10-19", "normal"),
    ("2026-10-20", "normal"),
    ("2026-10-21", "normal"),
    ("2026-10-22", "incomplete"),
    ("2026-10-23", "normal"),
    ("2026-10-26", "normal"),
]
ACTUAL_KW = {
    ("00:45", 0): 410.0,
    ("01:00", 0): 380.0,
    ("01:15", 0): 360.0,
    ("01:30", 0): 420.0,
    ("01:45", 0): 500.0,
    ("01:00", 1): 510.0,
    ("01:15", 1): 340.0,
    ("01:30", 1): 330.0,
    ("01:45", 1): 450.0,
    ("02:00", 0): 480.0,
}


def _utc_text(value: datetime) -> str:
    return value.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _event_intervals(zone: ZoneInfo) -> list[tuple[str, int, datetime]]:
    start = datetime.fromisoformat(f"{EVENT_DATE}T00:45:00").replace(
        tzinfo=zone, fold=0
    )
    end = datetime.fromisoformat(f"{EVENT_DATE}T02:15:00").replace(
        tzinfo=zone, fold=0
    )
    cursor = start.astimezone(ZoneInfo("UTC"))
    result = []
    while cursor < end.astimezone(ZoneInfo("UTC")):
        local = cursor.astimezone(zone)
        result.append((local.strftime("%H:%M"), local.fold, cursor))
        cursor += timedelta(minutes=15)
    return result


def main() -> None:
    rng = random.Random(SEED)
    zone = ZoneInfo(TIMEZONE)
    rows = []
    for date_text, status in BASELINE_DAYS:
        for clock, base_kw in CLOCK_PROFILE.items():
            if status == "incomplete" and clock == "01:15":
                continue
            local = datetime.fromisoformat(f"{date_text}T{clock}:00").replace(
                tzinfo=zone
            )
            kw = max(1.0, float(base_kw + rng.randint(-35, 35)))
            rows.append(
                ("westgate-plaza", local.astimezone(ZoneInfo("UTC")), kw / 4.0)
            )
    for clock, fold, timestamp in _event_intervals(zone):
        rows.append(("westgate-plaza", timestamp, ACTUAL_KW[(clock, fold)] / 4.0))
    rows.sort(key=lambda item: (item[1], item[0]))

    root = Path(__file__).resolve().parents[1]
    data_dir = root / "environment" / "workspace" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "events.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "event_id",
                "site_id",
                "start_local",
                "end_local",
                "timezone",
                "committed_kw",
                "rate_usd_per_kwh",
            ]
        )
        writer.writerow(
            [
                "evt-fall-01",
                "westgate-plaza",
                "2026-11-01T00:45:00",
                "2026-11-01T02:15:00",
                TIMEZONE,
                "190",
                "0.92",
            ]
        )
    with (data_dir / "baseline_days.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "status"])
        writer.writerows(BASELINE_DAYS)
    with (data_dir / "readings.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["site_id", "timestamp_utc", "kwh"])
        for site_id, timestamp, kwh in rows:
            writer.writerow([site_id, _utc_text(timestamp), f"{kwh:.3f}"])
    with (data_dir / "portfolio.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "target_mwh",
                "budget_usd",
                "max_events",
                "demand_charge_usd_per_kw",
            ]
        )
        writer.writerow(["0.3", "500", "1", "0.5"])


if __name__ == "__main__":
    main()
