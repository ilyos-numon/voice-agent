"""Measure BM25 retrieval on a human-style (colloquial) evaluation JSONL, with intent-leak metrics.

Usage (from repo root):
  uv run python scripts/eval_colloquial.py --eval tests/fixtures/faq_eval_colloquial.jsonl --validate
  uv run python scripts/eval_colloquial.py --faq data/faq/faq.jsonl --eval tests/fixtures/faq_eval_colloquial.jsonl

--validate checks the schema only (no search, no leak): prints "SCHEMA OK n=.. n_answerable=.. n_none=..".
Schema errors print "SCHEMA_ERROR line=<n> reason=<text>" per problem and exit 2.
Otherwise prints a SUMMARY line, one `miss` line per overall-top1 miss (ids only, never FAQ text)
and `RESULT MEASURED`, always exit 0 (accuracy is reported, not gated).

Leak = share of the intent's (FAQ question) character bigrams that also appear in the query.
Strict schema applies only to files whose rows carry `qid`; legacy rows (faq_eval.jsonl) get
qid=f"L{line}", traits=[] and only the expected_id existence check.
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOW_LEAK = 0.34
MIN_ROWS, MAX_ROWS = 30, 50
MIN_NONE, MAX_NONE = 5, 10
MIN_QUERY, MAX_QUERY = 4, 80
MIN_ID_NUM = 6
TRAITS = frozenset({"typo", "ellipsis", "indirect", "spoken"})
KINDS = ("colloquial", "none")
STRICT_KEYS = ("qid", "query", "expected_id", "kind", "traits")


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    rank = max(1, -(-len(s) * p // 100))
    return s[int(rank) - 1]


def bigrams(s: str) -> set[str]:
    t = "".join(ch for ch in unicodedata.normalize("NFC", s).lower() if ch.isalnum())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def leak(query: str, intent: str) -> float:
    b = bigrams(intent)
    return 0.0 if not b else len(b & bigrams(query)) / len(b)


def _id_num(faq_id: str) -> int | None:
    try:
        return int(faq_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


def is_strict(rows: list[dict[str, Any]]) -> bool:
    return any("qid" in r for r in rows)


def _validate_strict_row(r: dict[str, Any], faq_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    missing = [k for k in STRICT_KEYS if k not in r]
    if missing:
        return [f"missing keys {','.join(missing)}"]
    q = r["query"]
    if not isinstance(q, str) or not (MIN_QUERY <= len(q) <= MAX_QUERY):
        reasons.append(f"query length must be {MIN_QUERY}-{MAX_QUERY}")
    kind, eid = r["kind"], r["expected_id"]
    if kind not in KINDS:
        reasons.append(f"kind must be one of {','.join(KINDS)}")
    elif kind == "none" and eid is not None:
        reasons.append("kind none requires expected_id null")
    elif kind == "colloquial":
        if not isinstance(eid, str):
            reasons.append("kind colloquial requires expected_id")
        elif eid not in faq_ids:
            reasons.append(f"expected_id {eid} not in faq")
        else:
            num = _id_num(eid)
            if num is None or num < MIN_ID_NUM:
                reasons.append(f"expected_id number must be >= {MIN_ID_NUM}")
    traits = r["traits"]
    if not isinstance(traits, list) or not traits:
        reasons.append("traits must be a non-empty list")
    elif not set(traits) <= TRAITS:
        reasons.append(f"unknown traits {','.join(sorted(set(map(str, traits)) - TRAITS))}")
    return reasons


def validate_rows(rows: list[dict[str, Any]], faq_ids: set[str]) -> list[str]:
    errs: list[str] = []
    if not is_strict(rows):
        for line, r in enumerate(rows, start=1):
            eid = r.get("expected_id")
            if eid is not None and eid not in faq_ids:
                errs.append(f"line={line} reason=expected_id {eid} not in faq")
        return errs

    seen_qid: dict[Any, int] = {}
    seen_eid: dict[Any, int] = {}
    for line, r in enumerate(rows, start=1):
        for reason in _validate_strict_row(r, faq_ids):
            errs.append(f"line={line} reason={reason}")
        qid = r.get("qid")
        if qid in seen_qid:
            errs.append(f"line={line} reason=duplicate qid {qid} (first line={seen_qid[qid]})")
        else:
            seen_qid[qid] = line
        if r.get("kind") == "colloquial" and r.get("expected_id") is not None:
            eid = r["expected_id"]
            if eid in seen_eid:
                errs.append(f"line={line} reason=duplicate expected_id {eid} (first line={seen_eid[eid]})")
            else:
                seen_eid[eid] = line
    n = len(rows)
    n_none = sum(1 for r in rows if r.get("kind") == "none")
    if not (MIN_ROWS <= n <= MAX_ROWS):
        errs.append(f"line=0 reason=row count {n} not in {MIN_ROWS}-{MAX_ROWS}")
    if not (MIN_NONE <= n_none <= MAX_NONE):
        errs.append(f"line=0 reason=none count {n_none} not in {MIN_NONE}-{MAX_NONE}")
    return errs


def load_eval(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errs: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                errs.append(f"line={line_no} reason=invalid json ({e.msg})")
                continue
            if not isinstance(obj, dict):
                errs.append(f"line={line_no} reason=row is not an object")
                continue
            rows.append(obj)
    return rows, errs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--faq", type=Path, default=ROOT / "data" / "faq" / "faq.jsonl")
    p.add_argument("--eval", type=Path, default=ROOT / "tests" / "fixtures" / "faq_eval_colloquial.jsonl")
    p.add_argument("--validate", action="store_true")
    return p.parse_args(argv)


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from app.pipeline.bm25 import BM25Retriever, load_faq_any

    items = load_faq_any(args.faq)
    by_id = {it.id: it for it in items}

    rows, errs = load_eval(args.eval)
    errs += validate_rows(rows, set(by_id))
    if errs:
        for e in errs:
            print(f"SCHEMA_ERROR {e}")
        return 2

    strict = is_strict(rows)
    for line, r in enumerate(rows, start=1):
        if not strict:
            r["qid"] = f"L{line}"
            r["traits"] = []
    answerable = [r for r in rows if r["expected_id"] is not None]
    none_rows = [r for r in rows if r["expected_id"] is None]
    n, n_ans, n_none = len(rows), len(answerable), len(none_rows)

    if args.validate:
        print(f"SCHEMA OK n={n} n_answerable={n_ans} n_none={n_none}")
        return 0

    retriever = BM25Retriever(items)
    hit1 = hit3 = none_ok = overall = 0
    leaks: list[float] = []
    low = [0, 0]  # [hits, count]
    high = [0, 0]
    misses: list[str] = []
    for r in rows:
        ids = [h.id for h in retriever.search(r["query"], top_k=3)]
        eid = r["expected_id"]
        got = ids[0] if ids else "none"
        if eid is None:
            ok = not ids
            none_ok += ok
            lk_txt = "na"
        else:
            ok = ids[:1] == [eid]
            hit1 += ok
            hit3 += eid in ids
            lk = leak(r["query"], by_id[eid].question)
            leaks.append(lk)
            bucket = low if lk < LOW_LEAK else high
            bucket[0] += ok
            bucket[1] += 1
            lk_txt = f"{lk:.2f}"
        overall += ok
        if not ok:
            misses.append(f"miss qid={r['qid']} expected={eid or 'none'} got={got} leak={lk_txt}")

    leak_mean = sum(leaks) / len(leaks) if leaks else 0.0
    print(
        f"n={n} n_answerable={n_ans} n_none={n_none} "
        f"top1={_ratio(hit1, n_ans):.3f} top3={_ratio(hit3, n_ans):.3f} "
        f"none_correct={_ratio(none_ok, n_none):.3f} overall_top1={_ratio(overall, n):.3f} "
        f"leak_mean={leak_mean:.3f} leak_p50={percentile(leaks, 50):.3f} "
        f"top1_low_leak={_ratio(low[0], low[1]):.3f} n_low_leak={low[1]} "
        f"top1_high_leak={_ratio(high[0], high[1]):.3f} n_high_leak={high[1]}"
    )
    for miss in misses:
        print(miss)
    print("RESULT MEASURED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
