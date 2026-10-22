"""Input loading for the settlement prototype."""

from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class InputError(ValueError):
    """Raised when a settlement input cannot be used."""


def _rows(path: Path, expected: list[str]) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != expected:
            raise InputError(f"{path.name}: unexpected columns")
        return list(reader)


def _number(text: str, label: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise InputError(f"{label}: expected a finite number")
    return value


def load_inputs(
    input_dir: Path,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Load the three settlement tables."""
    event_rows = _rows(
        input_dir / "events.csv",
        [
            "event_id",
            "site_id",
            "start_local",
            "end_local",
            "timezone",
            "committed_kw",
            "rate_usd_per_kwh",
        ],
    )
    events = []
    for row in event_rows:
        ZoneInfo(row["timezone"])
        datetime.fromisoformat(row["start_local"])
        datetime.fromisoformat(row["end_local"])
        events.append(
            {
                **row,
                "committed_kw": _number(row["committed_kw"], "committed_kw"),
                "rate_usd_per_kwh": _number(
                    row["rate_usd_per_kwh"], "rate_usd_per_kwh"
                ),
            }
        )

    reading_rows = _rows(
        input_dir / "readings.csv", ["site_id", "timestamp_utc", "kwh"]
    )
    readings = []
    for row in reading_rows:
        kwh = _number(row["kwh"], "kwh")
        timestamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
        readings.append(
            {
                "site_id": row["site_id"],
                "timestamp_utc": timestamp,
                "kwh": kwh,
                "kw": kwh * 4.0,
            }
        )

    day_rows = _rows(input_dir / "baseline_days.csv", ["date", "status"])
    baseline_days = [dict(row) for row in day_rows]

    portfolio_rows = _rows(
        input_dir / "portfolio.csv",
        ["target_mwh", "budget_usd", "max_events", "demand_charge_usd_per_kw"],
    )
    if len(portfolio_rows) != 1:
        raise InputError("portfolio.csv: expected exactly one row")
    portfolio = {
        "target_mwh": _number(
            portfolio_rows[0]["target_mwh"], "target_mwh"
        ),
        "budget_usd": _number(
            portfolio_rows[0]["budget_usd"], "budget_usd"
        ),
        "max_events": int(portfolio_rows[0]["max_events"]),
        "demand_charge_usd_per_kw": _number(
            portfolio_rows[0]["demand_charge_usd_per_kw"],
            "demand_charge_usd_per_kw",
        ),
    }
    return events, readings, baseline_days, portfolio
