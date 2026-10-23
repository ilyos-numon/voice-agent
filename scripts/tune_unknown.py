"""Pick MIN_QUERY_COVERAGE for unknown detection by the design D3 rule.

Usage (from repo root):
  uv run --no-sync python scripts/tune_unknown.py --preset civil-kiosk --eval tests/fixtures/faq_eval_colloquial.jsonl

For each candidate value prints
  cov=<v> sentinels_ok=<bool> kept_answerable=<a>/<b> none_caught=<c>/<d>
and finally "CHOSEN <v>": the largest value where both sentinels stay grounded and at least 90 %
of answerable rows whose BM25 top1 is correct stay grounded (0.10 if none qualifies).
Only counts and ids are printed, never query or FAQ text. Argument errors exit 2.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.compose import is_unknown
from app.agents.presets import load_presets
from app.agents.retrieval import ChunkIndex

CANDIDATES = (0.10, 0.15, 0.20, 0.25, 0.30)
SENTINELS = ("주민등록등본 떼려면 뭐 필요해요?", "등본 떼려면 뭐 필요해요?")
MIN_KEPT_RATIO = 0.9
FALLBACK = 0.10


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--preset", required=True)
    ap.add_argument("--eval", required=True, type=Path)
    ap.add_argument("--presets-dir", type=Path, default=ROOT / "data" / "presets")
    args = ap.parse_args(argv)

    presets = {p.preset_id: p for p in load_presets(args.presets_dir)}
    if args.preset not in presets:
        print(f"unknown preset: {args.preset}", file=sys.stderr)
        return 2
    if not args.eval.is_file():
        print(f"eval file not found: {args.eval}", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in args.eval.read_text(encoding="utf-8").splitlines() if line.strip()]

    index = ChunkIndex(presets[args.preset].agent.chunks)
    answerable = []
    nones = []
    for row in rows:
        cands = index.search(row["query"])
        if row.get("expected_id") is None:
            nones.append((row["query"], cands))
        elif cands and cands[0].chunk.chunk_id == row["expected_id"]:
            answerable.append((row["query"], cands))
    sentinels = [(q, index.search(q)) for q in SENTINELS]

    chosen = FALLBACK
    for v in CANDIDATES:
        sentinels_ok = all(not is_unknown(q, c, v) for q, c in sentinels)
        kept = sum(not is_unknown(q, c, v) for q, c in answerable)
        caught = sum(is_unknown(q, c, v) for q, c in nones)
        print(
            f"cov={v:.2f} sentinels_ok={sentinels_ok} kept_answerable={kept}/{len(answerable)} "
            f"none_caught={caught}/{len(nones)}"
        )
        if sentinels_ok and answerable and kept / len(answerable) >= MIN_KEPT_RATIO:
            chosen = v
    print(f"CHOSEN {chosen:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
