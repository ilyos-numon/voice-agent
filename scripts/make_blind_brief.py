"""Build a blind writing brief (answer excerpts without intent names) from a normalized FAQ JSONL.

Usage (from repo root):
  uv run python scripts/make_blind_brief.py --out .ai/tasks/<T>/logs/blind_brief.jsonl

Each output line is {"target_id", "category", "answer"} (answer truncated to 400 chars).
The FAQ question (intent name) is never written. Same input -> same bytes.
Only counts are printed; FAQ text never goes to stdout.
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIN_ID_NUM = 6
MIN_ANSWER_CHARS = 40
MAX_ANSWER_CHARS = 400


def id_num(faq_id: str) -> int:
    return int(faq_id.rsplit("-", 1)[1])


def candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [
        r
        for r in rows
        if id_num(r["id"]) >= MIN_ID_NUM and len(str(r.get("answer", "")).strip()) >= MIN_ANSWER_CHARS
    ]
    return sorted(out, key=lambda r: id_num(r["id"]))


def build_brief(rows: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, str]]:
    cands = candidates(rows)
    k = min(n, len(cands))
    if k < n:
        print(f"warning: only {len(cands)} candidates < n={n}; using {k}", file=sys.stderr)
    picked = sorted(random.Random(seed).sample(cands, k), key=lambda r: id_num(r["id"]))
    return [
        {
            "target_id": r["id"],
            "category": str(r.get("category", "")),
            "answer": str(r["answer"])[:MAX_ANSWER_CHARS],
        }
        for r in picked
    ]


def load_rows(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--faq", type=Path, default=ROOT / "data" / "faq" / "faq.jsonl")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=38)
    p.add_argument("--seed", type=int, default=20261023)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_rows(args.faq)
    out = build_brief(rows, args.n, args.seed)
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    print(f"faq={len(rows)} candidates={len(candidates(rows))} brief={len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
