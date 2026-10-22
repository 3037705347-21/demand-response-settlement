"""Strict input parsing for demand-response settlement."""

from __future__ import annotations

import csv
import math
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .calendar import expand_event


EVENT_FIELDS = [
    "event_id",
    "site_id",
    "start_local",
    "end_local",
    "timezone",
    "committed_kw",
    "rate_usd_per_kwh",
]
READING_FIELDS = ["site_id", "timestamp_utc", "kwh"]
DAY_FIELDS = ["date", "status"]
STATUSES = {"normal", "maintenance", "incomplete", "event"}


class InputError(ValueError):
    """Raised when a settlement input cannot be used."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label}: expected a non-empty string")
    return value.strip()


def _number(value: str, label: str, *, positive: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{label}: expected a number") from exc
    if not math.isfinite(parsed):
        raise InputError(f"{label}: expected a finite number")
    if positive and parsed <= 0:
        raise InputError(f"{label}: expected a positive number")
    if not positive and parsed < 0:
        raise InputError(f"{label}: expected a non-negative number")
    return parsed


def _rows(path: Path, expected: list[str]) -> list[dict]:
    if not path.is_file():
        raise InputError(f"missing {path.name}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected:
            raise InputError(f"{path.name}: unexpected columns")
        rows = list(reader)
    if not rows:
        raise InputError(f"{path.name}: no rows")
    return rows


def _aligned(value: datetime, label: str) -> None:
    if value.second != 0 or value.microsecond != 0 or value.minute % 15 != 0:
        raise InputError(f"{label}: expected a fifteen-minute boundary")


def _load_events(input_dir: Path) -> list[dict]:
    events = []
    seen = set()
    for index, row in enumerate(
        _rows(input_dir / "events.csv", EVENT_FIELDS), start=2
    ):
        event_id = _text(row.get("event_id"), f"events.csv:{index} event_id")
        site_id = _text(row.get("site_id"), f"events.csv:{index} site_id")
        if event_id in seen:
            raise InputError(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        try:
            zone = ZoneInfo(_text(row.get("timezone"), "timezone"))
        except Exception as exc:
            raise InputError(f"events.csv:{index} unknown timezone") from exc
        del zone
        try:
            start = datetime.fromisoformat(_text(row.get("start_local"), "start_local"))
            end = datetime.fromisoformat(_text(row.get("end_local"), "end_local"))
        except ValueError as exc:
            raise InputError(f"events.csv:{index} invalid local time") from exc
        if start.tzinfo is not None or end.tzinfo is not None:
            raise InputError("event local times must not contain an offset")
        _aligned(start, "start_local")
        _aligned(end, "end_local")
        if end <= start:
            raise InputError(f"events.csv:{index} event must end after it starts")
        events.append(
            {
                "event_id": event_id,
                "site_id": site_id,
                "start_local": row["start_local"].strip(),
                "end_local": row["end_local"].strip(),
                "timezone": row["timezone"].strip(),
                "committed_kw": _number(
                    row.get("committed_kw"), "committed_kw", positive=True
                ),
                "rate_usd_per_kwh": _number(
                    row.get("rate_usd_per_kwh"), "rate_usd_per_kwh"
                ),
            }
        )
    return events


def _load_readings(input_dir: Path) -> list[dict]:
    readings = []
    seen = set()
    for index, row in enumerate(
        _rows(input_dir / "readings.csv", READING_FIELDS), start=2
    ):
        site_id = _text(row.get("site_id"), "readings.csv site_id")
        raw_timestamp = _text(row.get("timestamp_utc"), "timestamp_utc")
        if not raw_timestamp.endswith("Z"):
            raise InputError(f"readings.csv:{index} timestamp must end with Z")
        try:
            timestamp = datetime.fromisoformat(
                raw_timestamp[:-1] + "+00:00"
            ).astimezone(timezone.utc)
        except ValueError as exc:
            raise InputError(f"readings.csv:{index} invalid UTC timestamp") from exc
        _aligned(timestamp, f"readings.csv:{index} timestamp")
        key = (site_id, timestamp)
        if key in seen:
            raise InputError(
                f"readings.csv:{index} duplicate site timestamp "
                f"{site_id} {raw_timestamp}"
            )
        seen.add(key)
        kwh = _number(row.get("kwh"), f"readings.csv:{index} kwh")
        readings.append(
            {
                "site_id": site_id,
                "timestamp_utc": timestamp,
                "kwh": kwh,
                "kw": kwh * 4.0,
            }
        )
    return readings


def _load_days(input_dir: Path) -> list[dict]:
    days = []
    seen = set()
    for index, row in enumerate(
        _rows(input_dir / "baseline_days.csv", DAY_FIELDS), start=2
    ):
        raw_date = _text(row.get("date"), "baseline date")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise InputError(f"baseline_days.csv:{index} invalid date") from exc
        if parsed.isoformat() != raw_date:
            raise InputError(f"baseline_days.csv:{index} date is not canonical")
        if raw_date in seen:
            raise InputError(f"baseline_days.csv:{index} duplicate date {raw_date}")
        seen.add(raw_date)
        status = _text(row.get("status"), "baseline status")
        if status not in STATUSES:
            raise InputError(f"baseline_days.csv:{index} unknown status {status}")
        days.append({"date": raw_date, "status": status})
    return days


def _load_portfolio(input_dir: Path) -> dict:
    rows = _rows(
        input_dir / "portfolio.csv",
        ["target_mwh", "budget_usd", "max_events", "demand_charge_usd_per_kw"],
    )
    if len(rows) != 1:
        raise InputError("portfolio.csv: expected exactly one row")
    row = rows[0]
    target_mwh = _number(row.get("target_mwh"), "target_mwh")
    budget_usd = _number(row.get("budget_usd"), "budget_usd")
    demand_charge = _number(
        row.get("demand_charge_usd_per_kw"), "demand_charge_usd_per_kw"
    )
    raw_count = _text(row.get("max_events"), "max_events")
    try:
        max_events = int(raw_count)
    except ValueError as exc:
        raise InputError("max_events: expected an integer") from exc
    if str(max_events) != raw_count or max_events < 0:
        raise InputError("max_events: expected a non-negative integer")
    return {
        "target_mwh": target_mwh,
        "budget_usd": budget_usd,
        "max_events": max_events,
        "demand_charge_usd_per_kw": demand_charge,
    }


def load_inputs(
    input_dir: Path,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Load and fully validate all settlement tables."""
    events = _load_events(input_dir)
    readings = _load_readings(input_dir)
    baseline_days = _load_days(input_dir)
    portfolio = _load_portfolio(input_dir)
    by_key = {
        (reading["site_id"], reading["timestamp_utc"]) for reading in readings
    }
    for event in events:
        for interval in expand_event(event):
            if (event["site_id"], interval["start_utc"]) not in by_key:
                raise InputError(
                    f"{event['event_id']}: missing interval reading at "
                    f"{interval['start_utc'].isoformat()}"
                )
    return events, readings, baseline_days, portfolio
