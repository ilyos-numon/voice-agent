import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from app.agents import retrieval
from app.agents.compose import (
    FRIENDLY_PREFIX,
    SENTENCE_LIMIT,
    UNKNOWN_TEXT,
    is_unknown,
    matches_avoid,
    shape_sentences,
    system_prompt,
    unknown_sentence,
)
from app.agents.models import AgentSettings
from app.agents.presets import Preset, load_presets
from app.agents.retrieval import ChunkIndex

ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = ROOT / "data" / "presets"
SENTS = ["첫째 문장입니다.", "둘째 문장입니다.", "셋째 문장입니다.", "넷째 문장입니다.", "다섯째 문장입니다."]


@pytest.fixture(scope="module")
def presets() -> dict[str, Preset]:
    return {p.preset_id: p for p in load_presets(PRESETS_DIR, clock=lambda: 1000.0)}


def test_civil_kiosk_sentinel_is_known(presets: dict[str, Preset]) -> None:
    q = "등본 떼려면 뭐 필요해요?"
    cands = ChunkIndex(presets["civil-kiosk"].agent.chunks).search(q)
    assert cands[0].chunk.chunk_id == "faq-001"
    assert is_unknown(q, cands) is False


def test_restaurant_offtopic_is_unknown(presets: dict[str, Preset]) -> None:
    q = "주민등록등본 발급 방법 알려줘"
    cands = ChunkIndex(presets["restaurant"].agent.chunks).search(q)
    assert is_unknown(q, cands) is True


def test_no_candidates_is_unknown() -> None:
    assert is_unknown("아무거나", []) is True


def test_matches_avoid_ignores_space_and_case() -> None:
    assert matches_avoid("주식 투자 어떻게 해요", ["주식투자"])
    assert matches_avoid("VIP 라운지 어디예요", ["vip라운지"])
    assert not matches_avoid("주차 어디예요", ["주식", "vip"])
    assert not matches_avoid("주차", [])


@pytest.mark.parametrize(("length", "n"), [("one_sentence", 1), ("short", 2), ("detailed", 4)])
def test_sentence_limit(length: str, n: int) -> None:
    s = dataclasses.replace(AgentSettings(), answer_length=length, tone="concise")  # type: ignore[arg-type]
    assert SENTENCE_LIMIT[length] == n
    assert shape_sentences(SENTS, s) == SENTS[:n]


def test_friendly_prefix_on_first_sentence_only() -> None:
    out = shape_sentences(SENTS, AgentSettings(tone="friendly", answer_length="short"))
    assert out == [FRIENDLY_PREFIX + SENTS[0], SENTS[1]]


def test_concise_has_no_prefix() -> None:
    out = shape_sentences(SENTS, AgentSettings(tone="concise", answer_length="detailed"))
    assert not any(s.startswith(FRIENDLY_PREFIX) for s in out)


def test_unknown_sentence_policies() -> None:
    assert unknown_sentence(AgentSettings(when_unknown="say_unknown")) == UNKNOWN_TEXT
    s = AgentSettings(when_unknown="handoff", handoff_message="창구 직원에게 물어봐 주세요.")
    assert unknown_sentence(s) == "창구 직원에게 물어봐 주세요."


def test_system_prompt_contents() -> None:
    s = AgentSettings(persona_name="주문 도우미", answer_length="detailed", avoid_topics=("주식",))
    p = system_prompt(s)
    assert "주문 도우미" in p
    assert "4문장" in p
    assert "주식" in p
    assert "근거 밖" in p


def test_tune_unknown_chosen_matches_constant() -> None:
    out = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "tune_unknown.py"),
            "--preset",
            "civil-kiosk",
            "--eval",
            str(ROOT / "tests" / "fixtures" / "faq_eval_colloquial.jsonl"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    last = out.stdout.strip().splitlines()[-1]
    assert last.startswith("CHOSEN ")
    assert float(last.split()[1]) == retrieval.MIN_QUERY_COVERAGE
