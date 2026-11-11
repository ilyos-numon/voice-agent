from pathlib import Path

import pytest

from app.agents.models import Agent, AgentSettings, Chunk
from app.agents.presets import Preset, load_presets
from app.agents.questions import ScoreQuestion, make_questions

ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = ROOT / "data" / "presets"


@pytest.fixture(scope="module")
def presets() -> dict[str, Preset]:
    return {p.preset_id: p for p in load_presets(PRESETS_DIR, clock=lambda: 1000.0)}


def _agent(chunks: tuple[Chunk, ...]) -> Agent:
    return Agent("ag_000000000000", "테스트", None, AgentSettings(), chunks, 0.0, None)


def _csv_chunks(k: int) -> tuple[Chunk, ...]:
    return tuple(
        Chunk(f"q-{i:03d}", f"질문 {i}번 내용은 무엇인가요?", f"답변 {i}번입니다.",
              f"질문 {i}번 내용은 무엇인가요?", "faq_csv")
        for i in range(1, k + 1)
    )


def test_same_input_same_output(presets: dict[str, Preset]) -> None:
    for p in presets.values():
        a = make_questions(p.agent, 30)
        b = make_questions(p.agent, 30)
        assert a == b


def test_chunk_order_does_not_matter() -> None:
    chunks = _csv_chunks(12)
    a = make_questions(_agent(chunks), 10)
    b = make_questions(_agent(tuple(reversed(chunks))), 10)
    assert a == b


def test_civil_kiosk_n30_is_15_15(presets: dict[str, Preset]) -> None:
    qs = make_questions(presets["civil-kiosk"].agent, 30)
    assert len(qs) == 30
    assert sum(q.style == "verbatim" for q in qs) == 15
    assert sum(q.style == "colloquial" for q in qs) == 15
    assert [q.qid for q in qs] == [f"sq-{i:02d}" for i in range(1, 31)]
    assert len({q.expected_chunk_id for q in qs}) == 15
    for q in qs:
        assert isinstance(q, ScoreQuestion)
        assert q.text.strip()


def test_few_chunks_all_included() -> None:
    chunks = _csv_chunks(4)
    qs = make_questions(_agent(chunks), 30)
    assert len(qs) <= 8
    assert {q.expected_chunk_id for q in qs} == {c.chunk_id for c in chunks}


def test_even_spacing_over_sorted_ids() -> None:
    chunks = _csv_chunks(20)
    qs = make_questions(_agent(chunks), 10)
    ids = sorted({q.expected_chunk_id for q in qs})
    assert ids == ["q-001", "q-005", "q-009", "q-013", "q-017"]


def test_verbatim_and_colloquial_per_chunk() -> None:
    chunks = _csv_chunks(10)
    qs = make_questions(_agent(chunks), 20)
    by_chunk: dict[str, dict[str, str]] = {}
    for q in qs:
        by_chunk.setdefault(q.expected_chunk_id, {})[q.style] = q.text
    titles = {c.chunk_id: c.title for c in chunks}
    for cid, styles in by_chunk.items():
        assert styles["verbatim"] == titles[cid]
        assert styles["colloquial"] != styles["verbatim"]


def test_colloquial_rules_rotate() -> None:
    chunks = _csv_chunks(10)
    qs = [q for q in make_questions(_agent(chunks), 20) if q.style == "colloquial"]
    # p0 ... 알려주세요 / p1 ... 어떻게 해요? / p2 ... 궁금해요 / p3 붙여쓰기 / p4 구어 어미
    assert qs[0].text.endswith("알려주세요")
    assert qs[1].text.endswith("어떻게 해요?")
    assert qs[2].text.endswith("궁금해요")
    assert " " not in qs[3].text
    assert qs[4].text.endswith("돼요?") or qs[4].text.endswith("어떻게 해요?")
    assert qs[5].text.endswith("알려주세요")


def test_text_origin_verbatim_is_first_sentence() -> None:
    chunk = Chunk("c-001", "주차 안내", "건물 지하 1층에 주차장이 있습니다. 방문객은 2시간 무료입니다.",
                  "주차 안내\n건물 지하 1층에 주차장이 있습니다. 방문객은 2시간 무료입니다.", "text")
    qs = make_questions(_agent((chunk,)), 10)
    assert qs[0].style == "verbatim"
    assert qs[0].text == "건물 지하 1층에 주차장이 있습니다."
    assert qs[1].style == "colloquial" and qs[1].text != qs[0].text


def test_colloquial_falls_through_when_same_as_verbatim() -> None:
    # 한 어절 + 물음표: p3 붙여쓰기 결과가 verbatim과 같다 → 다음 규칙
    chunks = tuple(
        Chunk(f"q-{i:03d}", "주차?", "주차장이 있습니다.", "주차?", "faq_csv") for i in range(1, 5)
    )
    qs = make_questions(_agent(chunks), 8)
    for q in qs:
        if q.style == "colloquial":
            assert q.text != "주차?"


def test_odd_n_and_empty() -> None:
    qs = make_questions(_agent(_csv_chunks(20)), 11)
    assert len(qs) <= 12 and len({q.expected_chunk_id for q in qs}) == 6
    assert make_questions(_agent(()), 30) == []
