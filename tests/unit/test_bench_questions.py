import importlib
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2] / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))
mq = importlib.import_module("make_questions")


def _faq(n: int, start_len: int = 10, step: int = 10) -> list[dict]:
    return [
        {"id": f"faq-{i:03d}", "question": f"q{i}", "answer": "가" * (start_len + i * step)}
        for i in range(n)
    ]


def test_range_filter_excludes_short_and_long() -> None:
    faq = _faq(60)  # lengths 10..600
    out = mq.select_questions(faq, [], n=10, min_chars=40, max_chars=500)
    assert len(out) == 10
    assert all(40 <= q["answer_chars"] <= 500 for q in out)


def test_eval_first_and_duplicate_ids_dropped() -> None:
    faq = _faq(60)
    eval_rows = [
        {"query": "a", "expected_id": "faq-010", "kind": "seed"},
        {"query": "b", "expected_id": "faq-010", "kind": "seed"},
        {"query": "c", "expected_id": "faq-001", "kind": "p0"},  # len 20, not candidate
        {"query": "d", "expected_id": "faq-020", "kind": "p0"},
    ]
    out = mq.select_questions(faq, eval_rows, n=5, min_chars=40, max_chars=500)
    evals = [q for q in out if q["origin"] == "eval"]
    assert {(q["id"], q["query"]) for q in evals} == {("faq-010", "a"), ("faq-020", "d")}
    ids = [q["id"] for q in out]
    assert len(ids) == len(set(ids)) == 5


def test_quantile_sample_count_and_endpoints() -> None:
    faq = _faq(60)
    eval_rows = [{"query": "x", "expected_id": "faq-010", "kind": "p0"}]
    out = mq.select_questions(faq, eval_rows, n=7, min_chars=40, max_chars=500)
    faqs = [q for q in out if q["origin"] == "faq"]
    assert len(faqs) == 6
    assert faqs[0]["answer_chars"] == 40 and faqs[-1]["answer_chars"] == 500
    assert all(q["query"] == f"q{int(q['id'][4:])}" for q in faqs)


def test_sorted_and_deterministic() -> None:
    faq = list(reversed(_faq(60)))
    eval_rows = [{"query": "x", "expected_id": "faq-030", "kind": "p0"}]
    a = mq.select_questions(faq, eval_rows, n=12, min_chars=40, max_chars=500)
    b = mq.select_questions(faq, eval_rows, n=12, min_chars=40, max_chars=500)
    assert a == b
    keys = [(q["answer_chars"], q["id"]) for q in a]
    assert keys == sorted(keys)
    assert set(a[0]) == {"id", "query", "answer_chars", "origin"}
