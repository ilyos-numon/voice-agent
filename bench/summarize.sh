#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BEFORE=bench/results/before.jsonl
AFTER=bench/results/after.jsonl
OUT_DIR=bench/results
while [ $# -gt 0 ]; do
  case "$1" in
    --before) BEFORE="$2"; shift 2 ;;
    --after) AFTER="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
for f in "$BEFORE" "$AFTER"; do
  [ -f "$f" ] || { echo "input not found: $f" >&2; exit 1; }
done
mkdir -p "$OUT_DIR"
uv run --no-sync python bench/summarize.py --before "$BEFORE" --after "$AFTER" --out "$OUT_DIR/summary.md"
uv run --no-sync python bench/plot.py --before "$BEFORE" --after "$AFTER" --out "$OUT_DIR/waterfall.svg"
