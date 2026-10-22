import json
import unicodedata
from pathlib import Path

import pytest

from app.pipeline.bm25 import BM25Index, BM25Retriever, load_faq_any, tokenize
from app.pipeline.types import FaqItem

FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "faq" / "sample_faq.json"


@pytest.fixture
def retriever() -> BM25Retriever:
    return BM25Retriever.from_path(FAQ_PATH)


def _row(i: str, question: str = "질문") -> dict[str, str]:
    return {"id": i, "question": question, "answer": "답변", "source": "테스트"}


def test_tokenize_korean_bigrams() -> None:
    assert tokenize("주민등록등본 떼려면 뭐 필요해요?") == [
        "주민", "민등", "등록", "록등", "등본", "떼려", "려면", "뭐", "필요", "요해", "해요",
    ]  # fmt: skip


def test_tokenize_empty_and_ascii() -> None:
    assert tokenize("") == []
    assert tokenize("A-B 1.5") == ["a", "b", "1", "5"]


def test_tokenize_nfc() -> None:
    text = "주민등록등본 발급"
    nfd = unicodedata.normalize("NFD", text)
    assert nfd != text
    assert tokenize(nfd) == tokenize(text)


def test_idf_rarer_term_higher() -> None:
    index = BM25Index([["a", "b"], ["a", "c"], ["a", "d"]])
    assert index.idf("b") > index.idf("a") > 0.0


def test_idf_unknown_term_zero() -> None:
    index = BM25Index([["a", "b"]])
    assert index.idf("zz") == 0.0


def test_score_sorted_desc_and_positive_only() -> None:
    index = BM25Index([["x", "y"], ["a", "b"], ["a", "a", "b"], ["q"]])
    result = index.score(["a", "b"])
    assert [d for d, _ in result] == [2, 1]
    scores = [s for _, s in result]
    assert scores == sorted(scores, reverse=True)
    assert all(s > 0 for s in scores)


def test_score_empty_query() -> None:
    index = BM25Index([["a"]])
    assert index.score([]) == []


def test_tie_lower_index_first() -> None:
    items = [FaqItem(**_row("faq-a", "같은 질문")), FaqItem(**_row("faq-b", "같은 질문"))]
    r = BM25Retriever(items)
    assert [it.id for it in r.search("같은 질문")] == ["faq-a", "faq-b"]


def test_search_sample_faq001(retriever: BM25Retriever) -> None:
    hits = retriever.search("주민등록등본 떼려면 뭐 필요해요?")
    assert hits[0].id == "faq-001"


def test_search_whisper_variant_faq001(retriever: BM25Retriever) -> None:
    hits = retriever.search("주민등록등본 때려면 뭐 필요해요?")
    assert hits[0].id == "faq-001"


def test_search_xyzzy_empty(retriever: BM25Retriever) -> None:
    assert retriever.search("xyzzy") == []


def test_search_top_k(retriever: BM25Retriever) -> None:
    query = "주민등록등본 가족관계증명서 인감증명서 무인발급기 수수료"
    assert len(retriever.search(query)) == 3
    assert len(retriever.search(query, top_k=1)) == 1
    assert len(retriever.search(query, top_k=10)) == 5


def test_load_jsonl_ignores_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "faq.jsonl"
    rows = [{**_row("faq-001"), "category": "민원", "key": "k1"}, _row("faq-002")]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n\n", "utf-8")
    items = load_faq_any(path)
    assert [it.id for it in items] == ["faq-001", "faq-002"]
    assert items[0] == FaqItem(**_row("faq-001"))


def test_load_json_list() -> None:
    items = load_faq_any(FAQ_PATH)
    assert len(items) == 5
    assert items[0].id == "faq-001"


def test_load_missing_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "faq.jsonl"
    bad = _row("faq-002")
    del bad["answer"]
    path.write_text(json.dumps(_row("faq-001")) + "\n" + json.dumps(bad) + "\n", "utf-8")
    with pytest.raises(ValueError, match=r"faq\.jsonl:2: missing answer"):
        load_faq_any(path)


def test_load_duplicate_id_raises(tmp_path: Path) -> None:
    path = tmp_path / "faq.json"
    path.write_text(json.dumps([_row("faq-001"), _row("faq-001")]), "utf-8")
    with pytest.raises(ValueError, match="duplicate id: faq-001"):
        load_faq_any(path)
