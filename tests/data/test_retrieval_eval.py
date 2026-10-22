import json
import time
from pathlib import Path

import pytest

from app.pipeline.bm25 import BM25Retriever, load_faq_any
from app.pipeline.types import FaqItem

ROOT = Path(__file__).resolve().parents[2]
FAQ_PATH = ROOT / "data" / "faq" / "faq.jsonl"
EVAL_PATH = ROOT / "tests" / "fixtures" / "faq_eval.jsonl"
SAMPLE_PATH = ROOT / "data" / "faq" / "sample_faq.json"

TOP1_MIN = 0.70
TOP3_MIN = 0.90
P50_MAX_MS = 50.0
MIN_ROWS = 500


def _require(path: Path) -> None:
    if not path.exists():
        pytest.fail("run ./scripts/prepare_data.sh")


@pytest.fixture(scope="module")
def items() -> list[FaqItem]:
    _require(FAQ_PATH)
    return load_faq_any(FAQ_PATH)


@pytest.fixture(scope="module")
def retriever(items: list[FaqItem]) -> BM25Retriever:
    return BM25Retriever(items)


@pytest.fixture(scope="module")
def eval_rows() -> list[dict[str, str]]:
    _require(EVAL_PATH)
    with open(EVAL_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _p50(values: list[float]) -> float:
    s = sorted(values)
    return s[max(1, -(-len(s) * 50 // 100)) - 1]


def test_sentinel_exact_hits_faq001(retriever: BM25Retriever) -> None:
    hits = retriever.search("주민등록등본 떼려면 뭐 필요해요?")
    assert hits and hits[0].id == "faq-001"


def test_sentinel_whisper_variant_hits_faq001(retriever: BM25Retriever) -> None:
    hits = retriever.search("주민등록등본 때려면 뭐 필요해요?")
    assert hits and hits[0].id == "faq-001"


def test_unrelated_query_returns_empty(retriever: BM25Retriever) -> None:
    assert retriever.search("xyzzy") == []


def test_eval_set_accuracy(retriever: BM25Retriever, eval_rows: list[dict[str, str]]) -> None:
    assert eval_rows
    hit1 = hit3 = 0
    for r in eval_rows:
        ids = [h.id for h in retriever.search(r["query"], top_k=3)]
        hit1 += ids[:1] == [r["expected_id"]]
        hit3 += r["expected_id"] in ids
    top1 = hit1 / len(eval_rows)
    top3 = hit3 / len(eval_rows)
    print(f"n_eval={len(eval_rows)} top1={top1:.3f} top3={top3:.3f}")
    assert top1 >= TOP1_MIN
    assert top3 >= TOP3_MIN


def test_retrieve_p50_under_limit(retriever: BM25Retriever, eval_rows: list[dict[str, str]]) -> None:
    times: list[float] = []
    for r in eval_rows:
        t = time.perf_counter()
        retriever.search(r["query"], top_k=3)
        times.append((time.perf_counter() - t) * 1000)
    p50 = _p50(times)
    print(f"retrieve_p50_ms={p50:.3f}")
    assert p50 < P50_MAX_MS


def test_scale_unique_ids_and_synthetic_head(items: list[FaqItem]) -> None:
    print(f"docs={len(items)}")
    assert len(items) >= MIN_ROWS
    assert len({it.id for it in items}) == len(items)
    sample = load_faq_any(SAMPLE_PATH)
    assert items[: len(sample)] == sample
