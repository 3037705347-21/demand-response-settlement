"""Command-line entry point for the settlement prototype."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path

from .model import InputError, load_inputs
from .portfolio import select_portfolio
from .settlement import settle


def _write_outputs(
    output_dir: Path, settlement: dict, portfolio: dict
) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".dr-settle-", dir=output_dir.parent
    ) as temporary:
        staging = Path(temporary)
        with (staging / "settlement.json").open("w", encoding="utf-8") as handle:
            json.dump(settlement, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with (staging / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["event_id", "site_id", "reduction_kwh", "eligible_kwh", "payment_usd"]
            )
            for event in settlement["events"]:
                totals = event["totals"]
                writer.writerow(
                    [
                        event["event_id"],
                        event["site_id"],
                        f"{totals['reduction_kwh']:.3f}",
                        f"{totals['eligible_kwh']:.3f}",
                        f"{totals['payment_usd']:.3f}",
                    ]
                )
        with (staging / "portfolio.json").open("w", encoding="utf-8") as handle:
            json.dump(portfolio, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        output_dir.mkdir(parents=True, exist_ok=True)
        os.replace(staging / "settlement.json", output_dir / "settlement.json")
        os.replace(staging / "summary.csv", output_dir / "summary.csv")
        os.replace(staging / "portfolio.json", output_dir / "portfolio.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        events, readings, baseline_days, limits = load_inputs(Path(args.input_dir))
        result = settle(events, readings, baseline_days)
        portfolio = select_portfolio(result["events"], limits)
    except (InputError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"settlement failed: {exc}", file=__import__("sys").stderr)
        return 1
    try:
        _write_outputs(Path(args.output_dir), result, portfolio)
    except OSError as exc:
        print(f"cannot write output: {exc}", file=__import__("sys").stderr)
        return 1
    return 0
