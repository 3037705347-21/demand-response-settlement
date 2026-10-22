#!/bin/bash
set -u

reward_file=/logs/verifier/reward.txt
mkdir -p /logs/verifier
echo "0" > "$reward_file"

write_reward_zero() {
  echo "0" > "$reward_file"
}
trap 'write_reward_zero; exit 130' INT TERM HUP

if ! python -m pip install --user --no-cache-dir --disable-pip-version-check \
  --no-index --find-links /tests/wheels \
  --require-hashes --only-binary=:all: -r /tests/requirements.txt; then
  write_reward_zero
  exit 0
fi

cd /workspace || exit 0
results=/logs/verifier/results.xml
rm -f "$results"
python -m pytest -q /tests/test_outputs.py --junitxml="$results" \
  > /logs/verifier/pytest.log 2>&1

python - "$results" "$reward_file" <<'PY'
import sys
import xml.etree.ElementTree as ET

results, reward_file = sys.argv[1], sys.argv[2]
try:
    root = ET.parse(results).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    cases = suite.findall("testcase") if suite is not None else []
    total = len(cases)
    passed = sum(
        1
        for case in cases
        if case.find("failure") is None
        and case.find("error") is None
        and case.find("skipped") is None
    )
    reward = passed / total if total else 0.0
except (OSError, ET.ParseError, TypeError, ZeroDivisionError):
    reward = 0.0
with open(reward_file, "w", encoding="utf-8") as handle:
    handle.write(f"{reward:.6f}\n")
PY

trap - INT TERM HUP
exit 0
