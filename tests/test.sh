#!/bin/bash
set -u

reward_file=/logs/verifier/reward.txt
trusted_python=/usr/local/bin/python
testsite=/logs/verifier/testsite
RESULTS_XML=/logs/verifier/results.xml
mkdir -p /logs/verifier
chmod u+w "$reward_file" 2>/dev/null || true
echo "0" > "$reward_file"

write_reward_zero() {
  chmod u+w "$reward_file" 2>/dev/null || true
  echo "0" > "$reward_file"
  chmod 0444 "$reward_file"
}
trap 'write_reward_zero; exit 130' INT TERM HUP

if ! "$trusted_python" -I -m pip install --no-cache-dir --disable-pip-version-check \
  --no-index --find-links /tests/wheels \
  --require-hashes --only-binary=:all: --target "$testsite" \
  -r /tests/requirements.txt; then
  write_reward_zero
  exit 0
fi

cd /workspace || exit 0
rm -f "$RESULTS_XML"
/usr/bin/timeout 240s /usr/bin/env -i \
  PATH=/usr/bin:/bin \
  HOME=/tmp \
  PYTHONPATH="$testsite" \
  PYTHONDONTWRITEBYTECODE=1 \
  "$trusted_python" -S -P -m pytest -q -p no:cacheprovider \
  /tests/test_outputs.py --junitxml="$RESULTS_XML" \
  > /logs/verifier/pytest.log 2>&1

if ! test -s "$RESULTS_XML"; then
  echo "INCOMPLETE: pytest produced no result report" >> /logs/verifier/pytest.log
  write_reward_zero
  exit 0
fi

"$trusted_python" -I -S - "$RESULTS_XML" "$reward_file" <<'PY'
import sys
import xml.etree.ElementTree as ET

results, reward_file = sys.argv[1], sys.argv[2]
total = 0
reward = 0.0
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
if total == 0:
    reward = 0.0
with open(reward_file, "w", encoding="utf-8") as handle:
    handle.write(f"{reward:.6f}\n")
PY

chmod 0444 "$reward_file"
trap - INT TERM HUP
exit 0
