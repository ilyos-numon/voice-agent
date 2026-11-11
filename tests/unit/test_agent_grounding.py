from pathlib import Path

import pytest

from app.agents.grounding import GROUNDING_MIN_OVERLAP, ground_sentences
from app.agents.models import Chunk
from app.agents.presets import Preset, load_presets
from app.agents.retrieval import (
    GENERIC_BIGRAMS,
    MIN_QUERY_COVERAGE,
    Candidate,
    ChunkIndex,
    query_coverage,
)
from app.pipeline.bm25 import tokenize
from app.pipeline.sentences import split_sentences

ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = ROOT / "data" / "presets"

CHUNK = Chunk(
    chunk_id="c-001",
    title="주차 안내",
    text="방문객 주차는 지하 2층에서 가능합니다. 주차 요금은 첫 30분 무료이고 이후 10분마다 500원입니다.",
    index_text="주차 안내\n방문객 주차는 지하 2층에서 가능합니다.",
    origin="text",
)
OTHER = Chunk(
    chunk_id="c-002",
    title="운영 시간",
    text="평일 오전 9시부터 오후 6시까지 운영합니다.",
    index_text="운영 시간",
    origin="text",
)


@pytest.fixture(scope="module")
def presets() -> dict[str, Preset]:
    return {p.preset_id: p for p in load_presets(PRESETS_DIR, clock=lambda: 1000.0)}


def _cands(*chunks: Chunk) -> list[Candidate]:
    return [Candidate(chunk=c, score=1.0, rank=i) for i, c in enumerate(chunks, start=1)]


def test_copied_sentence_is_supported_with_high_overlap() -> None:
    sent = "주차 요금은 첫 30분 무료이고 이후 10분마다 500원입니다."
    [g] = ground_sentences([sent], _cands(CHUNK, OTHER))
    assert g.supported
    assert g.index == 0 and g.text == sent
    assert g.evidence[0].chunk_id == "c-001"
    assert g.evidence[0].overlap >= 0.9
    assert g.evidence[0].title == "주차 안내"


def test_invented_sentence_is_not_supported() -> None:
    [g] = ground_sentences(["우주선 발사장은 화성 기지 근처에 있습니다."], _cands(CHUNK, OTHER))
    assert not g.supported
    assert g.evidence == ()


def test_quote_is_a_sentence_of_the_chunk() -> None:
    [g] = ground_sentences(["주차 요금은 첫 30분 무료입니다."], _cands(CHUNK))
    assert g.supported
    assert g.evidence[0].quote in split_sentences(CHUNK.text)
    assert g.evidence[0].quote.startswith("주차 요금은")


def test_friendly_prefix_is_ignored() -> None:
    sent = "방문객 주차는 지하 2층에서 가능합니다."
    [plain] = ground_sentences([sent], _cands(CHUNK))
    [prefixed] = ground_sentences(["네, " + sent], _cands(CHUNK))
    assert prefixed.text == "네, " + sent
    assert prefixed.evidence[0].overlap == plain.evidence[0].overlap == 1.0


def test_evidence_sorted_by_overlap_and_rounded() -> None:
    sent = "주차는 평일 오전 9시부터 오후 6시까지 운영합니다."
    [g] = ground_sentences([sent], _cands(CHUNK, OTHER), min_overlap=0.1)
    overlaps = [e.overlap for e in g.evidence]
    assert overlaps == sorted(overlaps, reverse=True)
    assert g.evidence[0].chunk_id == "c-002"
    assert all(round(o, 3) == o for o in overlaps)


def test_indexes_and_threshold_default() -> None:
    out = ground_sentences(["방문객 주차는 지하 2층에서 가능합니다.", "!!"], _cands(CHUNK))
    assert [g.index for g in out] == [0, 1]
    assert out[1].supported is False and out[1].evidence == ()
    assert GROUNDING_MIN_OVERLAP == 0.5


def test_search_ranks_descending_scores() -> None:
    chunks = [
        Chunk(f"q-00{i}", t, "답", t, "faq_csv")
        for i, t in enumerate(["주차 요금", "주차 요금 할인 주차", "운영 시간", "주차장 위치"], start=1)
    ]
    cands = ChunkIndex(chunks).search("주차 요금 할인", top_k=3)
    assert [c.rank for c in cands] == [1, 2, 3]
    scores = [c.score for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert cands[0].chunk.chunk_id == "q-002"


def test_search_no_hit_returns_empty() -> None:
    assert ChunkIndex([CHUNK]).search("우주선") == []


def test_query_coverage() -> None:
    assert query_coverage("", CHUNK) == 0.0
    assert query_coverage("!!", CHUNK) == 0.0
    assert query_coverage("주차 요금", CHUNK) == 1.0
    assert 0.0 < query_coverage("주차 우주선", CHUNK) < 1.0


def test_civil_kiosk_sentinel_top1(presets: dict[str, Preset]) -> None:
    cands = ChunkIndex(presets["civil-kiosk"].agent.chunks).search("등본 떼려면 뭐 필요해요?")
    assert cands[0].chunk.chunk_id == "faq-001"
    assert [c.rank for c in cands] == list(range(1, len(cands) + 1))


def _raw_coverage(query: str, chunk: Chunk) -> float:
    q = set(tokenize(query))
    return len(q & set(tokenize(chunk.title + "\n" + chunk.text))) / len(q)


def test_generic_bigrams_are_request_phrasing_only() -> None:
    assert {"방법", "알려", "세요", "해요"} <= GENERIC_BIGRAMS
    assert not {"필요", "발급", "주차", "등본"} & GENERIC_BIGRAMS


def test_restaurant_offtopic_gets_no_generic_credit(presets: dict[str, Preset]) -> None:
    q = "주민등록등본 발급 방법 알려줘"
    [q004] = [c for c in presets["restaurant"].agent.chunks if c.chunk_id == "q-004"]
    raw = _raw_coverage(q, q004)
    assert raw > 0.0
    assert query_coverage(q, q004) < raw
    assert query_coverage(q, q004) < MIN_QUERY_COVERAGE


def test_generic_only_query_is_zero() -> None:
    assert query_coverage("방법 알려주세요", CHUNK) == 0.0


@pytest.mark.parametrize("q", ["등본 떼려면 뭐 필요해요?", "주민등록등본 떼려면 뭐 필요해요?"])
def test_civil_sentinels_stay_above_threshold(presets: dict[str, Preset], q: str) -> None:
    cands = ChunkIndex(presets["civil-kiosk"].agent.chunks).search(q)
    assert cands[0].chunk.chunk_id == "faq-001"
    assert query_coverage(q, cands[0].chunk) >= MIN_QUERY_COVERAGE
