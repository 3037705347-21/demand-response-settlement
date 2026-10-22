#!/bin/sh
set -eu
for module in __init__.py __main__.py calendar.py baseline.py settlement.py portfolio.py model.py cli.py; do
  if [ -f "/solution/oracle/$module" ]; then
    install -m 0644 "/solution/oracle/$module" "/workspace/dr_settle/$module"
  fi
done
