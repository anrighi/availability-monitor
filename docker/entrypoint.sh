#!/bin/sh
set -eu

INTERVAL="${POLL_INTERVAL_SECONDS:-900}"
DATA_DIR="${APP_DATA_DIR:-/data}"
MONITOR_CMD="${MONITOR_CMD:-python /app/monitor.py --data-dir \"$DATA_DIR\"}"

mkdir -p "$DATA_DIR"

while true; do
  eval "$MONITOR_CMD" || true
  sleep "$INTERVAL"
done
