from pathlib import Path

import pytest

from app.agents.compose import is_unknown
from app.agents.knowledge import chunk_text, parse_faq_csv
from app.agents.retrieval import (
    GENERIC_BIGRAMS,
    PARTICLES,
    ChunkIndex,
    agent_tokenize,
    content_tokens,
)

SAMPLES = Path(__file__).parents[2] / "data" / "samples"
ROWS = 300
CHARS = 100_000


@pytest.fixture(scope="module")
def text_index() -> ChunkIndex:
    chunks, _ = chunk_text((SAMPLES / "fitness-center.txt").read_text(encoding="utf-8"), CHARS)
    return ChunkIndex(chunks)


@pytest.fixture(scope="module")
def csv_index() -> ChunkIndex:
    chunks, _ = parse_faq_csv((SAMPLES / "fitness-center.csv").read_text(encoding="utf-8"), ROWS, CHARS)
    return ChunkIndex(chunks)


def test_particles_longest_first() -> None:
    assert len(PARTICLES) == 27
    assert "가" not in PARTICLES
    assert [len(p) for p in PARTICLES] == sorted((len(p) for p in PARTICLES), reverse=True)
    assert PARTICLES[0] == "에서도"


def test_tokenize_strips_compound_particle() -> None:
    assert agent_tokenize("일요일에도") == ["일요", "요일"]


def test_tokenize_strips_topic_particle() -> None:
    assert agent_tokenize("주차는") == ["주차"]


def test_tokenize_lowercases_latin() -> None:
    assert agent_tokenize("PT") == ["pt"]


def test_tokenize_keeps_two_char_stem() -> None:
    assert agent_tokenize("나는") == ["나는"]


def test_generic_includes_isseoyo() -> None:
    assert "있어" in GENERIC_BIGRAMS
    assert "있어" not in content_tokens("수영장 있어요?")


def test_csv_index_text_includes_answer() -> None:
    chunks, _ = parse_faq_csv("질문,답변\n영업시간은?,9시부터 6시까지입니다.\n", ROWS, CHARS)
    assert "9시부터 6시까지입니다." in chunks[0].index_text
    assert chunks[0].index_text.startswith("영업시간은?")


TEXT_CASES = [
    ("일요일에도 문 열어요?", "운영 시간"),
    ("PT 당일 취소하면 어떻게 돼요?", "개인 트레이닝"),
    ("회원권 가격이 얼마예요?", "회원권과 요금"),
    ("주차 되나요?", "주차"),
    ("샤워실에 샴푸 있어요?", "샤워실"),
]

CSV_CASES = [
    ("일요일에도 문 열어요?", "운영 시간이 어떻게 되나요?"),
    ("PT 당일 취소하면 어떻게 돼요?", "PT 예약을 바꿀 수 있나요?"),
    ("회원권 가격이 얼마예요?", "회원권 가격이 얼마예요?"),
    ("주차 되나요?", "주차 되나요?"),
    ("샤워실에 샴푸 있어요?", "샤워실에 샴푸 있어요?"),
]


@pytest.mark.parametrize(("query", "title"), TEXT_CASES)
def test_fitness_text_top1(text_index: ChunkIndex, query: str, title: str) -> None:
    cands = text_index.search(query)
    assert cands[0].chunk.title == title
    assert not is_unknown(query, cands)


@pytest.mark.parametrize(("query", "title"), CSV_CASES)
def test_fitness_csv_top1(csv_index: ChunkIndex, query: str, title: str) -> None:
    cands = csv_index.search(query)
    assert cands[0].chunk.title == title
    assert not is_unknown(query, cands)


def test_fitness_pool_unknown_both(text_index: ChunkIndex, csv_index: ChunkIndex) -> None:
    q = "수영장 있어요?"
    assert is_unknown(q, text_index.search(q))
    assert is_unknown(q, csv_index.search(q))
