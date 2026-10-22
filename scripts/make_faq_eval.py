"""Build a deterministic retrieval evaluation set from a normalized FAQ JSONL.

Usage (from repo root):
  uv run python scripts/make_faq_eval.py --faq data/faq/faq.jsonl --out tests/fixtures/faq_eval.jsonl

Each output line is {"query", "expected_id", "kind"}: 2 sentinel lines (kind "seed") first,
then n rule-based paraphrases of sampled public questions. Same input -> same bytes.
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
MIN_WORDS = 2
MIN_CHARS = 6
NEAR_DUP_JACCARD = 0.5
RULES = ("p0_suffix_drop", "p1_swap", "p2_keywords", "p3_nospace")
SENTINELS: tuple[tuple[str, str], ...] = (
    ("주민등록등본 떼려면 뭐 필요해요?", "faq-001"),
    ("주민등록등본 때려면 뭐 필요해요?", "faq-001"),
)


def id_num(faq_id: str) -> int:
    return int(faq_id.rsplit("-", 1)[1])


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.pipeline.bm25 import tokenize

    grams = [set(tokenize(r["question"])) for r in rows]
    postings: dict[str, list[int]] = {}
    for i, bg in enumerate(grams):
        for t in bg:
            postings.setdefault(t, []).append(i)

    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        q = r["question"].strip()
        if id_num(r["id"]) < MIN_ID_NUM or len(q.split()) < MIN_WORDS or len(q) < MIN_CHARS:
            continue
        others = {j for t in grams[i] for j in postings.get(t, []) if j != i}
        if any(_jaccard(grams[i], grams[j]) >= NEAR_DUP_JACCARD for j in others):
            continue
        out.append(r)
    return sorted(out, key=lambda r: id_num(r["id"]))


def p0_suffix_drop(q: str) -> str:
    words = [w[:-1] if len(w) >= 3 else w for w in q.split()]
    return " ".join(words) + " 알려주세요"


def p1_swap(q: str) -> str:
    words = q.split()
    if len(words) >= 2:
        words[0], words[1] = words[1], words[0]
    return " ".join(words) + " 어떻게 해요?"


def p2_keywords(q: str) -> str:
    words = q.split()
    top = sorted(range(len(words)), key=lambda i: (-len(words[i]), i))[:2]
    return " ".join(words[i] for i in sorted(top)) + " 궁금해요"


def p3_nospace(q: str) -> str:
    return "".join(q.split()) + "?"


RULE_FUNCS = {
    "p0_suffix_drop": p0_suffix_drop,
    "p1_swap": p1_swap,
    "p2_keywords": p2_keywords,
    "p3_nospace": p3_nospace,
}


def build_eval(rows: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, str]]:
    cands = candidates(rows)
    k = min(n, len(cands))
    if k < n:
        print(f"warning: only {len(cands)} candidates < n={n}; using {k}", file=sys.stderr)
    picked = random.Random(seed).sample(cands, k)
    out = [{"query": q, "expected_id": i, "kind": "seed"} for q, i in SENTINELS]
    for pos, r in enumerate(picked):
        kind = RULES[pos % len(RULES)]
        query = RULE_FUNCS[kind](r["question"].strip())
        out.append({"query": query, "expected_id": r["id"], "kind": kind})
    return out


def load_rows(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--faq", type=Path, default=ROOT / "data" / "faq" / "faq.jsonl")
    p.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "faq_eval.jsonl")
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, default=20261022)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_rows(args.faq)
    out = build_eval(rows, args.n, args.seed)
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    print(f"faq={len(rows)} candidates={len(candidates(rows))} eval={len(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
