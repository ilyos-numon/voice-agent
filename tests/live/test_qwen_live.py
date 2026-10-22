"""Real Qwen API calls (3 per run). Requires LLM_API_KEY."""
import json
import os
import re
from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline.llm_qwen import QwenLLM
from app.pipeline.sentences import split_sentences
from app.pipeline.types import FaqItem

FAQ = Path(__file__).resolve().parents[2] / "data" / "faq" / "faq.jsonl"
CASES = [
    ("faq-229", "시흥시 인구 궁금해요"),
    ("faq-020", "위반건축물 행정처분"),
    ("faq-001", "주민등록등본 발급에 필요한 것"),
]


def _item(faq_id: str) -> FaqItem:
    for line in FAQ.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d["id"] == faq_id:
            return FaqItem(id=d["id"], question=d["question"], answer=d["answer"], source=d["source"])
    raise AssertionError(f"{faq_id} not in faq.jsonl")


@pytest.fixture(scope="module")
def llm() -> QwenLLM:
    s = Settings()
    key = os.environ.get("LLM_API_KEY") or s.llm_api_key
    return QwenLLM(key, s.llm_base_url, s.llm_model, s.llm_timeout_s)


@pytest.mark.parametrize(("faq_id", "query"), CASES)
def test_live_answer_short_and_grounded(llm: QwenLLM, faq_id: str, query: str) -> None:
    item = _item(faq_id)
    answer = llm.answer(query, [item])
    sentences = split_sentences(answer)
    assert 1 <= len(sentences) <= 3
    if len(item.answer) >= 120:  # plan C4: shorter-than-source applies to long items
        assert len(answer) < len(item.answer)
    for num in re.findall(r"\d+", answer):
        assert num in item.answer
