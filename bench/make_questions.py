"""Build the deterministic benchmark question set (bench/questions.jsonl).

Usage (from repo root):
  uv run python bench/make_questions.py --faq data/faq/faq.jsonl \
      --eval tests/fixtures/faq_eval.jsonl --out bench/questions.jsonl

Rules: candidates = FAQ answers with min_chars <= len <= max_chars; eval queries first
(file order, one per id), then quantile samples by answer length. Sorted by
(answer_chars, id). No randomness. Only counts/lengths are printed.
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def select_questions(
    faq: list[dict], eval_rows: list[dict], n: int, min_chars: int, max_chars: int
) -> list[dict]:
    cands = {r["id"]: r for r in faq if min_chars <= len(r["answer"]) <= max_chars}
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in eval_rows:
        fid = row["expected_id"]
        if fid in cands and fid not in used and len(chosen) < n:
            used.add(fid)
            chosen.append(
                {"id": fid, "query": row["query"],
                 "answer_chars": len(cands[fid]["answer"]), "origin": "eval"}
            )
    rest = sorted(
        (r for r in cands.values() if r["id"] not in used),
        key=lambda r: (len(r["answer"]), r["id"]),
    )
    m = min(n - len(chosen), len(rest))
    if m > 0:
        if m == 1:
            idxs = [0]
        else:
            idxs = [round(i * (len(rest) - 1) / (m - 1)) for i in range(m)]
        for i in idxs:
            r = rest[i]
            chosen.append(
                {"id": r["id"], "query": r["question"],
                 "answer_chars": len(r["answer"]), "origin": "faq"}
            )
    chosen.sort(key=lambda q: (q["answer_chars"], q["id"]))
    return chosen


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--faq", type=Path, required=True)
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--min-chars", type=int, default=40)
    p.add_argument("--max-chars", type=int, default=500)
    a = p.parse_args()
    qs = select_questions(
        _read_jsonl(a.faq), _read_jsonl(a.eval), a.n, a.min_chars, a.max_chars
    )
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as f:
        for q in qs:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    lens = [q["answer_chars"] for q in qs]
    n_eval = sum(q["origin"] == "eval" for q in qs)
    print(
        f"questions={len(qs)} chars_min={min(lens)} p50={statistics.median(lens):g} "
        f"max={max(lens)} eval={n_eval} faq={len(qs) - n_eval}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
