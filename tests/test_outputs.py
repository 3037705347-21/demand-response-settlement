"""Independent end-to-end checks for commercial demand-response settlement."""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


WORKSPACE = Path(os.environ.get("DR_SETTLE_WORKSPACE", "/workspace"))
UTC = ZoneInfo("UTC")


def _utc_text(value: datetime) -> str:
    """Format one datetime as a UTC timestamp."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reading(
    date_text: str,
    clock: str,
    timezone: str,
    kw: float,
    site_id: str = "harbor-center",
) -> tuple[str, str, str]:
    """Build one quarter-hour reading from an average-power value."""
    zone = ZoneInfo(timezone)
    local = datetime.fromisoformat(f"{date_text}T{clock}:00").replace(tzinfo=zone)
    return site_id, _utc_text(local), f"{kw / 4.0:.3f}"


def _write_inputs(
    root: Path,
    events: list[list[str]],
    days: list[list[str]],
    readings: list[tuple[str, str, str]],
    portfolio: list[str] | None = None,
) -> Path:
    """Write one complete input directory."""
    source = root / "input"
    source.mkdir()
    with (source / "events.csv").open("w", encoding="utf-8", newline="") as handle:
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
        writer.writerows(events)
    with (source / "baseline_days.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "status"])
        writer.writerows(days)
    with (source / "readings.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["site_id", "timestamp_utc", "kwh"])
        writer.writerows(sorted(readings))
    with (source / "portfolio.csv").open(
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
        limits = list(portfolio or ["0", "999999", "100", "0"])
        if len(limits) == 3:
            limits.append("0")
        writer.writerow(limits)
    return source


def _run_inputs(source: Path, output: Path) -> dict:
    """Run the public entrypoint and capture both output artifacts."""
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "dr_settle",
            "--input-dir",
            str(source),
            "--output-dir",
            str(output),
        ],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
        timeout=30,
    )
    settlement_path = output / "settlement.json"
    summary_path = output / "summary.csv"
    payload = None
    if settlement_path.is_file():
        payload = json.loads(settlement_path.read_text(encoding="utf-8"))
    portfolio_path = output / "portfolio.json"
    return {
        "status": process.returncode,
        "payload": payload,
        "summary": (
            summary_path.read_text(encoding="utf-8")
            if summary_path.is_file()
            else None
        ),
        "settlement_exists": settlement_path.is_file(),
        "summary_exists": summary_path.is_file(),
        "portfolio": (
            json.loads(portfolio_path.read_text(encoding="utf-8"))
            if portfolio_path.is_file()
            else None
        ),
        "portfolio_exists": portfolio_path.is_file(),
        "stderr": process.stderr,
    }


def _run_temporary(
    events: list[list[str]],
    days: list[list[str]],
    readings: list[tuple[str, str, str]],
    portfolio: list[str] | None = None,
) -> dict:
    """Run one temporary input set and return its outcome."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = _write_inputs(root, events, days, readings, portfolio)
        return _run_inputs(source, root / "output")


def _run_shipped() -> dict:
    """Run the data set shipped in the workspace."""
    with tempfile.TemporaryDirectory() as temporary:
        return _run_inputs(WORKSPACE / "data", Path(temporary) / "output")


def _case_data(
    actual_kw: list[float], confounders: bool = True
) -> tuple[list[list[str]], list[list[str]], list[tuple[str, str, str]]]:
    """Build a normal-day settlement case with known top-five baselines."""
    timezone = "America/Los_Angeles"
    event = [
        [
            "evt-normal",
            "harbor-center",
            "2026-10-20T12:00:00",
            "2026-10-20T12:45:00",
            timezone,
            "180",
            "0.5",
        ]
    ]
    days = [
        ["2026-10-06", "normal"],
        ["2026-10-07", "normal"],
        ["2026-10-08", "normal"],
        ["2026-10-09", "normal"],
        ["2026-10-12", "normal"],
        ["2026-10-13", "normal"],
        ["2026-10-14", "normal"],
        ["2026-10-15", "normal"],
        ["2026-10-16", "maintenance"],
        ["2026-10-19", "incomplete"],
    ]
    normal_values = [
        (500.0, 550.0, 720.0),
        (520.0, 570.0, 720.0),
        (540.0, 590.0, 720.0),
        (560.0, 610.0, 720.0),
        (580.0, 630.0, 720.0),
        (600.0, 650.0, 720.0),
        (620.0, 670.0, 720.0),
        (640.0, 690.0, 720.0),
    ]
    if not confounders:
        normal_values = [(600.0, 650.0, 720.0)] * 8
    readings = []
    for (date_text, _status), values in zip(days[:8], normal_values, strict=True):
        readings.append(_reading(date_text, "12:00", timezone, values[0]))
        readings.append(_reading(date_text, "12:15", timezone, values[1]))
        readings.append(_reading(date_text, "12:30", timezone, values[2]))
    readings.append(_reading("2026-10-14", "11:45", timezone, 1000.0))
    decoy = 1000.0 if confounders else 600.0
    readings.append(_reading("2026-10-16", "12:00", timezone, decoy))
    readings.append(
        _reading("2026-10-16", "12:15", timezone, 1000.0 if confounders else 650.0)
    )
    readings.append(
        _reading("2026-10-16", "12:30", timezone, 1000.0 if confounders else 720.0)
    )
    readings.append(_reading("2026-10-19", "12:00", timezone, decoy))
    readings.append(
        _reading("2026-10-19", "12:30", timezone, 1000.0 if confounders else 720.0)
    )
    for clock, kw in zip(("12:00", "12:15", "12:30"), actual_kw, strict=True):
        readings.append(_reading("2026-10-20", clock, timezone, kw))
    return event, days, readings


def _spring_case() -> tuple[
    list[list[str]], list[list[str]], list[tuple[str, str, str]]
]:
    """Build a spring-forward event with three elapsed UTC intervals."""
    timezone = "America/Los_Angeles"
    event = [
        [
            "evt-spring",
            "north-garage",
            "2026-03-08T01:30:00",
            "2026-03-08T03:15:00",
            timezone,
            "120",
            "0.75",
        ]
    ]
    days = [
        ["2026-03-02", "normal"],
        ["2026-03-03", "normal"],
        ["2026-03-04", "normal"],
        ["2026-03-05", "normal"],
        ["2026-03-06", "normal"],
    ]
    readings = []
    for index, (date_text, _status) in enumerate(days):
        readings.append(
            _reading(date_text, "01:30", timezone, 500.0 + index, "north-garage")
        )
        readings.append(
            _reading(date_text, "01:45", timezone, 510.0 + index, "north-garage")
        )
        readings.append(
            _reading(date_text, "03:00", timezone, 520.0 + index, "north-garage")
        )
    for clock, kw in zip(("01:30", "01:45", "03:00"), (300.0, 320.0, 340.0), strict=True):
        readings.append(
            _reading("2026-03-08", clock, timezone, kw, "north-garage")
        )
    return event, days, readings


def _ambiguous_boundary_case() -> tuple[
    list[list[str]], list[list[str]], list[tuple[str, str, str]]
]:
    """Build a fall-back event whose start and end are both ambiguous."""
    timezone = "America/Los_Angeles"
    event = [
        [
            "evt-overlap",
            "east-market",
            "2026-11-01T01:00:00",
            "2026-11-01T01:45:00",
            timezone,
            "150",
            "0.8",
        ]
    ]
    days = [
        ["2026-10-27", "normal"],
        ["2026-10-28", "normal"],
        ["2026-10-29", "normal"],
        ["2026-10-30", "normal"],
        ["2026-10-31", "normal"],
    ]
    readings = []
    for index, (date_text, _status) in enumerate(days):
        for offset, clock in enumerate(("01:00", "01:15", "01:30", "01:45")):
            readings.append(
                _reading(
                    date_text,
                    clock,
                    timezone,
                    500.0 + index * 5.0 + offset,
                    "east-market",
                )
            )
    readings.extend(
        [
            ("east-market", "2026-11-01T08:00:00Z", "75.000"),
            ("east-market", "2026-11-01T08:15:00Z", "76.000"),
            ("east-market", "2026-11-01T08:30:00Z", "77.000"),
            ("east-market", "2026-11-01T08:45:00Z", "78.000"),
            ("east-market", "2026-11-01T09:00:00Z", "79.000"),
            ("east-market", "2026-11-01T09:15:00Z", "80.000"),
            ("east-market", "2026-11-01T09:30:00Z", "81.000"),
        ]
    )
    return event, days, readings


def _portfolio_case(
    specs: list[dict], portfolio: list[str]
) -> tuple[list[list[str]], list[list[str]], list[tuple[str, str, str]], list[str]]:
    """Build independent one-block candidate events for portfolio tests."""
    timezone = "UTC"
    event_date = "2026-10-20"
    days = [
        ["2026-10-13", "normal"],
        ["2026-10-14", "normal"],
        ["2026-10-15", "normal"],
        ["2026-10-16", "normal"],
        ["2026-10-17", "normal"],
    ]
    events = []
    readings: dict[tuple[str, str, str], float] = {}
    for spec in specs:
        start = datetime.fromisoformat(f"{event_date}T{spec['clock']}:00")
        end = start + _quarter_hour()
        events.append(
            [
                spec["id"],
                spec["site"],
                start.isoformat(),
                end.isoformat(),
                timezone,
                str(spec["committed"]),
                str(spec["rate"]),
            ]
        )
        for date_text, _status in days:
            readings[(spec["site"], date_text, spec["clock"])] = spec["baseline"]
        readings[(spec["site"], event_date, spec["clock"])] = spec["actual"]
    reading_rows = [
        (site, _utc_text(datetime.fromisoformat(f"{date_text}T{clock}:00").replace(
            tzinfo=ZoneInfo(timezone)
        )), f"{kw / 4.0:.3f}")
        for (site, date_text, clock), kw in readings.items()
    ]
    return events, days, reading_rows, portfolio


def _quarter_hour():
    """Return the fifteen-minute settlement block."""
    from datetime import timedelta

    return timedelta(minutes=15)


def test_c1_fallback_event_keeps_both_repeated_hours():
    """The shipped fall-back event expands to ten distinct elapsed intervals."""
    outcome = _run_shipped()
    assert outcome["status"] == 0 and outcome["payload"] is not None
    rows = outcome["payload"]["events"][0]["intervals"]
    expected = [
        "2026-11-01T00:45:00-07:00",
        "2026-11-01T01:00:00-07:00",
        "2026-11-01T01:15:00-07:00",
        "2026-11-01T01:30:00-07:00",
        "2026-11-01T01:45:00-07:00",
        "2026-11-01T01:00:00-08:00",
        "2026-11-01T01:15:00-08:00",
        "2026-11-01T01:30:00-08:00",
        "2026-11-01T01:45:00-08:00",
        "2026-11-01T02:00:00-08:00",
    ]
    assert [row["local_start"] for row in rows] == expected


def test_c1_spring_forward_skips_nonexistent_clock_hours():
    """A spring-forward event contains only intervals that occurred in UTC."""
    events, days, readings = _spring_case()
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    rows = outcome["payload"]["events"][0]["intervals"]
    assert [row["local_start"] for row in rows] == [
        "2026-03-08T01:30:00-08:00",
        "2026-03-08T01:45:00-08:00",
        "2026-03-08T03:00:00-07:00",
    ]


def test_c1_repeated_clock_matches_distinct_utc_readings():
    """The two 01:15 intervals retain their separate actual readings."""
    outcome = _run_shipped()
    assert outcome["status"] == 0 and outcome["payload"] is not None
    repeated = [
        row
        for row in outcome["payload"]["events"][0]["intervals"]
        if row["local_start"].startswith("2026-11-01T01:15:00")
    ]
    assert [row["actual_kw"] for row in repeated] == [360.0, 340.0]


def test_c1_ambiguous_boundaries_use_earlier_start_and_later_end():
    """An event inside the repeated hour includes both wall-clock passes."""
    events, days, readings = _ambiguous_boundary_case()
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    rows = outcome["payload"]["events"][0]["intervals"]
    assert [row["local_start"] for row in rows] == [
        "2026-11-01T01:00:00-07:00",
        "2026-11-01T01:15:00-07:00",
        "2026-11-01T01:30:00-07:00",
        "2026-11-01T01:45:00-07:00",
        "2026-11-01T01:00:00-08:00",
        "2026-11-01T01:15:00-08:00",
        "2026-11-01T01:30:00-08:00",
    ]


def test_c2_baseline_uses_top_five_complete_normal_days():
    """Maintenance and incomplete dates stay out of each wall-clock baseline."""
    events, days, readings = _case_data([450.0, 450.0, 450.0])
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    rows = outcome["payload"]["events"][0]["intervals"]
    assert [row["baseline_kw"] for row in rows] == [600.0, 650.0, 720.0]


def test_c2_fallback_folds_share_the_same_wall_clock_baseline():
    """Both repeated 01:15 rows use the single wall-clock baseline."""
    outcome = _run_shipped()
    assert outcome["status"] == 0 and outcome["payload"] is not None
    repeated = [
        row
        for row in outcome["payload"]["events"][0]["intervals"]
        if row["local_start"].startswith("2026-11-01T01:15:00")
    ]
    assert len(repeated) == 2
    assert repeated[0]["baseline_kw"] == repeated[1]["baseline_kw"]


def test_c2_baseline_does_not_mix_clocks_or_event_day():
    """Neighbouring clocks and the event date do not enter a baseline value."""
    events, days, readings = _case_data([450.0, 450.0, 450.0])
    event_site, event_timestamp, event_kwh = _reading(
        "2026-10-20", "12:00", "America/Los_Angeles", 5000.0
    )
    readings = [
        (site, event_timestamp, event_kwh)
        if timestamp == event_timestamp
        else (site, timestamp, value)
        for site, timestamp, value in readings
    ]
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    first = outcome["payload"]["events"][0]["intervals"][0]
    assert first["baseline_kw"] == 600.0


def test_c3_reduction_is_nonnegative_and_capacity_capped():
    """Reduction stops at zero and eligible capacity stops at the contract."""
    events, days, readings = _case_data([650.0, 500.0, 200.0], confounders=False)
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    rows = outcome["payload"]["events"][0]["intervals"]
    assert [row["reduction_kw"] for row in rows] == [0.0, 150.0, 520.0]
    assert [row["eligible_reduction_kw"] for row in rows] == [0.0, 150.0, 180.0]


def test_c3_payment_uses_quarter_hour_energy_and_event_rate():
    """Each interval payment applies 0.25 hours and the event rate."""
    events, days, readings = _case_data([650.0, 500.0, 200.0], confounders=False)
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    rows = outcome["payload"]["events"][0]["intervals"]
    assert [row["payment_usd"] for row in rows] == [0.0, 18.75, 22.5]


def test_c3_totals_and_summary_use_unrounded_interval_results():
    """JSON totals and the CSV row agree with the raw interval arithmetic."""
    events, days, readings = _case_data([650.0, 500.0, 200.0], confounders=False)
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] == 0 and outcome["payload"] is not None
    totals = outcome["payload"]["events"][0]["totals"]
    expected = {
        "reduction_kwh": 167.5,
        "eligible_kwh": 82.5,
        "payment_usd": 41.25,
    }
    assert totals == expected
    summary = list(csv.DictReader(outcome["summary"].splitlines()))
    assert summary == [
        {
            "event_id": "evt-normal",
            "site_id": "harbor-center",
            "reduction_kwh": "167.500",
            "eligible_kwh": "82.500",
            "payment_usd": "41.250",
        }
    ]


def test_c4_duplicate_utc_reading_leaves_no_output():
    """A repeated UTC timestamp rejects the whole request."""
    events, days, readings = _case_data([450.0, 450.0, 450.0])
    readings.append(readings[0])
    outcome = _run_temporary(events, days, readings)
    assert outcome["status"] != 0
    assert (
        not outcome["settlement_exists"]
        and not outcome["summary_exists"]
        and not outcome["portfolio_exists"]
    )


def test_c4_bad_timestamp_or_negative_energy_leaves_no_output():
    """Off-grid timestamps and negative energy never yield partial files."""
    events, days, readings = _case_data([450.0, 450.0, 450.0])
    off_grid = list(readings)
    off_grid[0] = (off_grid[0][0], "2026-10-06T19:05:00Z", off_grid[0][2])
    negative = list(readings)
    negative[0] = (negative[0][0], negative[0][1], "-1.000")
    off_grid_outcome = _run_temporary(events, days, off_grid)
    negative_outcome = _run_temporary(events, days, negative)
    assert off_grid_outcome["status"] != 0 and negative_outcome["status"] != 0
    assert all(
        not item["settlement_exists"]
        and not item["summary_exists"]
        and not item["portfolio_exists"]
        for item in (off_grid_outcome, negative_outcome)
    )


def test_c4_invalid_event_or_status_leaves_no_output():
    """A zero-length event or unknown day status is rejected before writing."""
    events, days, readings = _case_data([450.0, 450.0, 450.0])
    bad_event = [list(events[0])]
    bad_event[0][3] = bad_event[0][2]
    bad_days = [list(row) for row in days]
    bad_days[0][1] = "holiday"
    event_outcome = _run_temporary(bad_event, days, readings)
    status_outcome = _run_temporary(events, bad_days, readings)
    assert event_outcome["status"] != 0 and status_outcome["status"] != 0
    assert all(
        not item["settlement_exists"]
        and not item["summary_exists"]
        and not item["portfolio_exists"]
        for item in (event_outcome, status_outcome)
    )


def test_c5_portfolio_avoids_single_event_greedy_trap():
    """The cheapest feasible set can exclude the single largest event."""
    specs = [
        {
            "id": "evt-a",
            "site": "site-a",
            "clock": "12:00",
            "committed": 160.0,
            "rate": 0.225,
            "baseline": 400.0,
            "actual": 240.0,
        },
        {
            "id": "evt-b",
            "site": "site-b",
            "clock": "12:00",
            "committed": 120.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 280.0,
        },
        {
            "id": "evt-c",
            "site": "site-c",
            "clock": "12:15",
            "committed": 120.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 280.0,
        },
    ]
    events, days, readings, limits = _portfolio_case(
        specs, ["0.05", "12", "2"]
    )
    outcome = _run_temporary(events, days, readings, limits)
    assert outcome["status"] == 0 and outcome["portfolio"] is not None
    assert outcome["portfolio"]["selected_event_ids"] == ["evt-b", "evt-c"]
    assert outcome["portfolio"]["eligible_kwh"] == 60.0
    assert outcome["portfolio"]["payment_usd"] == 12.0


def test_c5_portfolio_excludes_overlapping_events_at_one_site():
    """Overlapping same-site candidates cannot both be selected."""
    specs = [
        {
            "id": "evt-a",
            "site": "site-x",
            "clock": "12:00",
            "committed": 160.0,
            "rate": 0.15,
            "baseline": 400.0,
            "actual": 240.0,
        },
        {
            "id": "evt-b",
            "site": "site-x",
            "clock": "12:00",
            "committed": 160.0,
            "rate": 0.15,
            "baseline": 400.0,
            "actual": 240.0,
        },
        {
            "id": "evt-c",
            "site": "site-y",
            "clock": "12:15",
            "committed": 120.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 280.0,
        },
    ]
    events, days, readings, limits = _portfolio_case(
        specs, ["0.06", "12", "2"]
    )
    outcome = _run_temporary(events, days, readings, limits)
    assert outcome["status"] == 0 and outcome["portfolio"] is not None
    assert outcome["portfolio"]["selected_event_ids"] == ["evt-a", "evt-c"]
    assert outcome["portfolio"]["eligible_kwh"] == 70.0


def test_c5_portfolio_uses_lexicographic_tie_break():
    """Equal cost and energy selections use the sorted event-id sequence."""
    specs = [
        {
            "id": "evt-z",
            "site": "site-z",
            "clock": "12:00",
            "committed": 120.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 280.0,
        },
        {
            "id": "evt-a",
            "site": "site-a",
            "clock": "12:15",
            "committed": 120.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 280.0,
        },
    ]
    events, days, readings, limits = _portfolio_case(
        specs, ["0.03", "6", "1"]
    )
    outcome = _run_temporary(events, days, readings, limits)
    assert outcome["status"] == 0 and outcome["portfolio"] is not None
    assert outcome["portfolio"]["selected_event_ids"] == ["evt-a"]


def test_c5_infeasible_portfolio_leaves_no_outputs():
    """A target above every feasible combination is rejected atomically."""
    specs = [
        {
            "id": "evt-a",
            "site": "site-a",
            "clock": "12:00",
            "committed": 160.0,
            "rate": 0.225,
            "baseline": 400.0,
            "actual": 240.0,
        }
    ]
    events, days, readings, limits = _portfolio_case(
        specs, ["0.1", "12", "1"]
    )
    outcome = _run_temporary(events, days, readings, limits)
    assert outcome["status"] != 0
    assert (
        not outcome["settlement_exists"]
        and not outcome["summary_exists"]
        and not outcome["portfolio_exists"]
    )


def test_c5_portfolio_scales_without_enumerating_all_subsets():
    """Thirty independent candidates resolve through grouped budget states."""
    specs = [
        {
            "id": f"evt-{index:02d}",
            "site": f"site-{index:02d}",
            "clock": "12:00",
            "committed": 100.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 300.0,
        }
        for index in range(30)
    ]
    events, days, readings, limits = _portfolio_case(
        specs, ["0.3", "60", "14"]
    )
    outcome = _run_temporary(events, days, readings, limits)
    assert outcome["status"] == 0 and outcome["portfolio"] is not None
    assert outcome["portfolio"]["selected_event_ids"] == [
        f"evt-{index:02d}" for index in range(12)
    ]
    assert outcome["portfolio"]["eligible_kwh"] == 300.0
    assert outcome["portfolio"]["payment_usd"] == 60.0


def test_c5_demand_charge_breaks_additive_portfolio_choice():
    """Coincident committed capacity can rule out the cheapest incentives."""
    specs = [
        {
            "id": "evt-a",
            "site": "site-a",
            "clock": "12:00",
            "committed": 100.0,
            "rate": 0.28,
            "baseline": 400.0,
            "actual": 300.0,
        },
        {
            "id": "evt-b",
            "site": "site-b",
            "clock": "12:00",
            "committed": 100.0,
            "rate": 0.28,
            "baseline": 400.0,
            "actual": 300.0,
        },
        {
            "id": "evt-c",
            "site": "site-c",
            "clock": "12:15",
            "committed": 100.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 300.0,
        },
        {
            "id": "evt-d",
            "site": "site-d",
            "clock": "12:15",
            "committed": 100.0,
            "rate": 0.2,
            "baseline": 400.0,
            "actual": 300.0,
        },
    ]
    events, days, readings, limits = _portfolio_case(
        specs, ["0.04", "30", "2", "0.1"]
    )
    outcome = _run_temporary(events, days, readings, limits)
    assert outcome["status"] == 0 and outcome["portfolio"] is not None
    assert outcome["portfolio"]["selected_event_ids"] == ["evt-a", "evt-c"]
    assert outcome["portfolio"]["eligible_kwh"] == 50.0
    assert outcome["portfolio"]["incentive_usd"] == 12.0
    assert outcome["portfolio"]["demand_charge_usd"] == 10.0
    assert outcome["portfolio"]["payment_usd"] == 22.0
