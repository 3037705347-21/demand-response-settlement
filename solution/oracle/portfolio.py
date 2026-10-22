"""Optimal candidate-event portfolio selection."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from .model import InputError


def _conflicts(left: dict, right: dict) -> bool:
    if left["site_id"] != right["site_id"]:
        return False
    left_starts = {row["start_utc"] for row in left["intervals"]}
    right_starts = {row["start_utc"] for row in right["intervals"]}
    return bool(left_starts & right_starts)


def _key(ids: tuple[str, ...], eligible: float, payment: float) -> tuple:
    return (round(payment, 6), round(-eligible, 6), ids)


def _site_options(events: list[dict]) -> list[tuple[int, int, float, tuple[str, ...]]]:
    """Enumerate conflict-free subsets for one site."""
    ordered = sorted(events, key=lambda event: event["event_id"])
    options: dict[tuple[int, int], tuple[float, tuple[str, ...]]] = {
        (0, 0): (0.0, ())
    }

    def visit(
        index: int,
        used: set[str],
        count: int,
        cost_mills: int,
        eligible: float,
        ids: tuple[str, ...],
    ) -> None:
        if index == len(ordered):
            key = (count, cost_mills)
            current = options.get(key)
            candidate = (eligible, ids)
            if (
                current is None
                or eligible > current[0] + 1e-9
                or (
                    abs(eligible - current[0]) <= 1e-9
                    and ids < current[1]
                )
            ):
                options[key] = candidate
            return
        visit(index + 1, used, count, cost_mills, eligible, ids)
        event = ordered[index]
        starts = {row["start_utc"] for row in event["intervals"]}
        if starts & used:
            return
        event_cost = int(round(float(event["totals"]["payment_usd"]) * 1000))
        visit(
            index + 1,
            used | starts,
            count + 1,
            cost_mills + event_cost,
            eligible + float(event["totals"]["eligible_kwh"]),
            ids + (event["event_id"],),
        )

    visit(0, set(), 0, 0, 0.0, ())
    return [
        (count, cost_mills, eligible, ids)
        for (count, cost_mills), (eligible, ids) in options.items()
    ]


def _coincident_peak(events: list[dict]) -> float:
    """Return the maximum committed capacity active at any UTC block."""
    profile: dict[str, float] = defaultdict(float)
    for event in events:
        for row in event["intervals"]:
            profile[row["start_utc"]] += event["committed_kw"]
    return max(profile.values(), default=0.0)


def _select_with_demand_charge(
    settled_events: list[dict], limits: dict
) -> tuple[tuple[str, ...], float, float]:
    """Search small demand-charge portfolios with a non-additive peak cost."""
    ordered = sorted(settled_events, key=lambda event: event["event_id"])
    target = limits["target_mwh"] * 1000.0
    budget = limits["budget_usd"]
    rate = limits["demand_charge_usd_per_kw"]
    best = None

    def visit(index: int, chosen: list[dict]) -> None:
        nonlocal best
        incentive = sum(event["totals"]["payment_usd"] for event in chosen)
        eligible = sum(event["totals"]["eligible_kwh"] for event in chosen)
        peak = _coincident_peak(chosen)
        total = incentive + peak * rate
        if total > budget + 1e-9:
            return
        if chosen and eligible + 1e-9 >= target:
            ids = tuple(sorted(event["event_id"] for event in chosen))
            key = (round(total, 6), round(-eligible, 6), ids)
            if best is None or key < best[0]:
                best = (key, ids, eligible, incentive, peak * rate, total)
        if index == len(ordered) or len(chosen) >= limits["max_events"]:
            return
        event = ordered[index]
        visit(index + 1, chosen)
        starts = {row["start_utc"] for row in event["intervals"]}
        conflict = any(
            event["site_id"] == item["site_id"]
            and starts & {row["start_utc"] for row in item["intervals"]}
            for item in chosen
        )
        if not conflict:
            visit(index + 1, chosen + [event])

    visit(0, [])
    if best is None:
        raise InputError("no candidate-event portfolio satisfies the limits")
    _, ids, eligible, incentive, demand_charge, total = best
    return ids, eligible, incentive, demand_charge, total


def select_portfolio(settled_events: list[dict], limits: dict) -> dict:
    """Find the lowest-cost feasible set, then apply stable tie-breaks."""
    if limits["demand_charge_usd_per_kw"] > 0:
        ids, eligible, incentive, demand_charge, total = _select_with_demand_charge(
            settled_events, limits
        )
        return {
            "selected_event_ids": list(ids),
            "eligible_kwh": round(eligible, 3),
            "incentive_usd": round(incentive, 3),
            "demand_charge_usd": round(demand_charge, 3),
            "payment_usd": round(total, 3),
        }
    by_site: dict[str, list[dict]] = defaultdict(list)
    for event in sorted(settled_events, key=lambda item: item["event_id"]):
        by_site[event["site_id"]].append(event)
    target_kwh = limits["target_mwh"] * 1000.0
    budget_mills = int(round(limits["budget_usd"] * 1000))
    max_events = limits["max_events"]
    states: dict[tuple[int, int], tuple[float, tuple[str, ...]]] = {
        (0, 0): (0.0, ())
    }
    for site_events in by_site.values():
        options = _site_options(site_events)
        next_states: dict[tuple[int, int], tuple[float, tuple[str, ...]]] = {}
        for (count, cost_mills), (eligible, ids) in states.items():
            for extra_count, extra_cost, extra_eligible, extra_ids in options:
                new_count = count + extra_count
                new_cost = cost_mills + extra_cost
                if new_count > max_events or new_cost > budget_mills:
                    continue
                combined_ids = tuple(sorted(ids + extra_ids))
                candidate = (eligible + extra_eligible, combined_ids)
                key = (new_count, new_cost)
                current = next_states.get(key)
                if (
                    current is None
                    or candidate[0] > current[0] + 1e-9
                    or (
                        abs(candidate[0] - current[0]) <= 1e-9
                        and candidate[1] < current[1]
                    )
                ):
                    next_states[key] = candidate
        states = next_states

    best = None
    for (count, cost_mills), (eligible, ids) in states.items():
        if eligible + 1e-9 < target_kwh:
            continue
        candidate = _key(ids, eligible, cost_mills / 1000.0)
        if best is None or candidate < best[0]:
            best = (candidate, ids, eligible, cost_mills)
    if best is None:
        raise InputError("no candidate-event portfolio satisfies the limits")
    _, best_ids, best_eligible, best_cost_mills = best
    return {
        "selected_event_ids": list(best_ids),
        "eligible_kwh": round(best_eligible, 3),
        "incentive_usd": round(best_cost_mills / 1000.0, 3),
        "demand_charge_usd": 0.0,
        "payment_usd": round(best_cost_mills / 1000.0, 3),
    }
