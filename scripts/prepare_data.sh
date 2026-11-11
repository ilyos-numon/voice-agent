#!/usr/bin/env bash
# Rebuild data/faq/faq.jsonl and tests/fixtures/faq_eval.jsonl, then check retrieval quality.
# Usage: scripts/prepare_data.sh [prepare_faq.py options, e.g. --skip-download]
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python scripts/prepare_faq.py "$@"
uv run python scripts/make_faq_eval.py --faq data/faq/faq.jsonl --out tests/fixtures/faq_eval.jsonl
uv run python scripts/eval_retrieval.py --faq data/faq/faq.jsonl --eval tests/fixtures/faq_eval.jsonl
