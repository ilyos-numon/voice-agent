"""Measure BM25 retrieval accuracy and latency on an evaluation JSONL.

Usage (from repo root):
  uv run python scripts/eval_retrieval.py --faq data/faq/faq.jsonl --eval tests/fixtures/faq_eval.jsonl

Prints a summary line, 3 sentinel lines, one `miss` line per top-1 miss (ids only, never FAQ text)
and `RESULT PASS|FAIL`. Exit 0 on PASS, 1 on FAIL.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SENTINELS: tuple[tuple[str, str | None], ...] = (
    ("주민등록등본 떼려면 뭐 필요해요?", "faq-001"),
    ("주민등록등본 때려면 뭐 필요해요?", "faq-001"),
    ("xyzzy", None),
)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    rank = max(1, -(-len(s) * p // 100))
    return s[int(rank) - 1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--faq", type=Path, default=ROOT / "data" / "faq" / "faq.jsonl")
    p.add_argument("--eval", type=Path, default=ROOT / "tests" / "fixtures" / "faq_eval.jsonl")
    p.add_argument("--top1-min", type=float, default=0.70)
    p.add_argument("--top3-min", type=float, default=0.90)
    p.add_argument("--p50-max-ms", type=float, default=50.0)
    p.add_argument("--build-max-ms", type=float, default=1000.0)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from app.pipeline.bm25 import BM25Retriever, load_faq_any

    items = load_faq_any(args.faq)
    t0 = time.perf_counter()
    retriever = BM25Retriever(items)
    build_ms = (time.perf_counter() - t0) * 1000

    with open(args.eval, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    hit1 = hit3 = 0
    times: list[float] = []
    misses: list[str] = []
    for r in rows:
        t = time.perf_counter()
        hits = retriever.search(r["query"], top_k=3)
        times.append((time.perf_counter() - t) * 1000)
        ids = [h.id for h in hits]
        if ids[:1] == [r["expected_id"]]:
            hit1 += 1
        else:
            got = ids[0] if ids else "none"
            misses.append(f"miss kind={r['kind']} expected={r['expected_id']} got={got}")
        if r["expected_id"] in ids:
            hit3 += 1

    n = len(rows)
    top1 = hit1 / n if n else 0.0
    top3 = hit3 / n if n else 0.0
    p50 = percentile(times, 50)
    p95 = percentile(times, 95)
    print(
        f"docs={len(items)} build_ms={build_ms:.1f} n_eval={n} top1={top1:.3f} top3={top3:.3f} "
        f"retrieve_p50_ms={p50:.3f} retrieve_p95_ms={p95:.3f}"
    )

    ok = True
    for query, expected in SENTINELS:
        hits = retriever.search(query, top_k=3)
        got = hits[0].id if hits else "none"
        passed = (got == expected) if expected is not None else not hits
        ok = ok and passed
        print(f'sentinel "{query}" -> {got} {"OK" if passed else "FAIL"}')
    for line in misses:
        print(line)

    ok = (
        ok
        and n > 0
        and top1 >= args.top1_min
        and top3 >= args.top3_min
        and p50 < args.p50_max_ms
        and build_ms < args.build_max_ms
    )
    print(f"RESULT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
