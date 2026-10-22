"""Run baseline, one-fix variants, and bypass specimens through the real test script."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


TASK = Path(__file__).resolve().parents[1]
IMAGE = "harbor-quality:demand-response-settlement"
MODULES = (
    "calendar.py",
    "baseline.py",
    "settlement.py",
    "portfolio.py",
    "model.py",
    "cli.py",
)


def run_command(args: list[str]) -> subprocess.CompletedProcess:
    """Run one local verification command."""
    return subprocess.run(args, text=True, capture_output=True, check=False)


def specimen(root: Path, label: str, files: tuple[str, ...], override=None) -> dict:
    """Run one source variant with an immutable workspace and test mount."""
    work = root / label / "workspace"
    shutil.copytree(TASK / "environment" / "workspace", work)
    for filename in files:
        shutil.copy2(
            TASK / "solution" / "oracle" / filename,
            work / "dr_settle" / filename,
        )
    if override is not None:
        override(work)
    logs = root / label / "logs" / "verifier"
    logs.mkdir(parents=True)
    (root / label).chmod(0o755)
    logs.parent.chmod(0o777)
    logs.chmod(0o777)
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        "10001:10001",
        "--network",
        "host",
        "-v",
        f"{work}:/workspace:ro",
        "-v",
        f"{TASK / 'tests'}:/tests:ro",
        "-v",
        f"{logs.parent}:/logs",
        IMAGE,
        "bash",
        "/tests/test.sh",
    ]
    outcome = run_command(command)
    reward_path = logs / "reward.txt"
    reward = (
        float(reward_path.read_text(encoding="utf-8").strip())
        if reward_path.exists()
        else None
    )
    evidence = TASK / "solution" / "evidence" / f"{label}.log"
    evidence.write_text(
        "Command: "
        + " ".join(command)
        + f"\nExit: {outcome.returncode}\nReward: {reward}\n"
        + "stdout:\n"
        + outcome.stdout
        + "\nstderr:\n"
        + outcome.stderr
        + "\n[pytest]\n"
        + (
            (logs / "pytest.log").read_text(encoding="utf-8")
            if (logs / "pytest.log").exists()
            else "missing"
        ),
        encoding="utf-8",
    )
    if reward is None:
        raise RuntimeError(f"{label}: no reward; inspect {evidence}")
    print(f"{label}: {reward}")
    return {"reward": reward, "evidence": str(evidence.relative_to(TASK))}


def empty_result(work: Path) -> None:
    """Replace settlement with an empty successful payload."""
    (work / "dr_settle" / "settlement.py").write_text(
        "def settle(events, readings, baseline_days):\n"
        "    return {'currency': 'USD', 'events': []}\n",
        encoding="utf-8",
    )


def replayed_sample(work: Path) -> None:
    """Replace settlement with the shipped demonstration result."""
    sample = (TASK / "solution" / "sample-result.json").read_text(encoding="utf-8")
    (work / "dr_settle" / "settlement.py").write_text(
        "import json\n"
        f"_SAMPLE = json.loads({sample!r})\n"
        "def settle(events, readings, baseline_days):\n"
        "    result = json.loads(json.dumps(_SAMPLE))\n"
        "    for index, event in enumerate(events):\n"
        "        if index < len(result['events']):\n"
        "            result['events'][index]['event_id'] = event['event_id']\n"
        "            result['events'][index]['site_id'] = event['site_id']\n"
        "    return result\n",
        encoding="utf-8",
    )


def truncated_payload(work: Path) -> None:
    """Return event totals without the interval evidence they summarize."""
    (work / "dr_settle" / "settlement.py").write_text(
        "def settle(events, readings, baseline_days):\n"
        "    rows = []\n"
        "    for event in events:\n"
        "        rows.append({'event_id': event['event_id'], "
        "'site_id': event['site_id'], 'intervals': [], "
        "'totals': {'reduction_kwh': 0.0, 'eligible_kwh': 0.0, 'payment_usd': 0.0}})\n"
        "    return {'currency': 'USD', 'events': rows}\n",
        encoding="utf-8",
    )


def main() -> None:
    """Build the package once and record every quality experiment."""
    build = run_command(
        ["docker", "build", "-q", "-t", IMAGE, str(TASK / "environment")]
    )
    if build.returncode:
        raise RuntimeError(build.stderr)
    (TASK / "solution" / "evidence").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dr-quality-") as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        baseline = specimen(root, "baseline", ())
        oracle = specimen(root, "oracle", MODULES)
        partials = [
            {"challenge_id": "C1", **specimen(root, "partial-c1", ("calendar.py",))},
            {"challenge_id": "C2", **specimen(root, "partial-c2", ("baseline.py",))},
            {"challenge_id": "C3", **specimen(root, "partial-c3", ("settlement.py",))},
            {"challenge_id": "C4", **specimen(root, "partial-c4", ("model.py",))},
            {"challenge_id": "C5", **specimen(root, "partial-c5", ("portfolio.py",))},
        ]
        bypasses = [
            {
                "id": "B1",
                "description": "返回空事件列表并正常退出",
                **specimen(root, "bypass-empty", (), empty_result),
            },
            {
                "id": "B2",
                "description": "固定回放随包演示结果",
                **specimen(root, "bypass-sample", (), replayed_sample),
            },
            {
                "id": "B3",
                "description": "只写空区间和全零汇总",
                **specimen(root, "bypass-truncated", (), truncated_payload),
            },
        ]
    report = {
        "baseline": baseline,
        "oracle": oracle,
        "partials": partials,
        "bypasses": bypasses,
    }
    (TASK / "solution" / "quality-gate-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if baseline["reward"] != 0 or oracle["reward"] != 1:
        raise RuntimeError("baseline/oracle gate failed")
    if any(not 0 < item["reward"] < 1 for item in partials):
        raise RuntimeError("partial gate failed")
    if any(item["reward"] == 1 for item in bypasses):
        raise RuntimeError("bypass gate failed")


if __name__ == "__main__":
    main()
