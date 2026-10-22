"""Candidate-event portfolio selection."""

from __future__ import annotations


def select_portfolio(settled_events: list[dict], limits: dict) -> dict:
    """Select all candidates and report their combined totals."""
    selected = sorted(settled_events, key=lambda event: event["event_id"])
    return {
        "selected_event_ids": [event["event_id"] for event in selected],
        "eligible_kwh": round(
            sum(event["totals"]["eligible_kwh"] for event in selected), 3
        ),
        "incentive_usd": round(
            sum(event["totals"]["payment_usd"] for event in selected), 3
        ),
        "demand_charge_usd": 0.0,
        "payment_usd": round(
            sum(event["totals"]["payment_usd"] for event in selected), 3
        ),
    }
