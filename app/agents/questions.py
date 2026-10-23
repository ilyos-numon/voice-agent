"""성적표 질문을 상담원 문서에서 규칙으로 만든다 (LLM 없음, 같은 입력 → 같은 출력).

구어 변형 규칙 p0~p3은 `scripts/make_faq_eval.py`를 옮긴 것이고 p4는 구어 어미다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.agents.models import Agent, Chunk
from app.pipeline.sentences import split_sentences

Style = Literal["verbatim", "colloquial"]
_TRAILING = "?？.!。 "
_ENDING_TAILS = ("요", "까", "다")


@dataclass(frozen=True)
class ScoreQuestion:
    qid: str
    text: str
    style: Style
    expected_chunk_id: str


def _core(q: str) -> str:
    return q.strip().rstrip(_TRAILING).strip()


def p0_suffix_drop(q: str) -> str:
    words = [w[:-1] if len(w) >= 3 else w for w in _core(q).split()]
    return " ".join(words) + " 알려주세요"


def p1_swap(q: str) -> str:
    words = _core(q).split()
    if len(words) >= 2:
        words[0], words[1] = words[1], words[0]
    return " ".join(words) + " 어떻게 해요?"


def p2_keywords(q: str) -> str:
    words = _core(q).split()
    top = sorted(range(len(words)), key=lambda i: (-len(words[i]), i))[:2]
    return " ".join(words[i] for i in sorted(top)) + " 궁금해요"


def p3_nospace(q: str) -> str:
    return "".join(_core(q).split()) + "?"


def p4_casual(q: str) -> str:
    words = _core(q).split()
    if len(words) >= 2 and words[-1].endswith(_ENDING_TAILS):
        words = words[:-1]
    body = " ".join(words)
    if "어떻게" in words:
        return body + " 돼요?"
    return body + " 어떻게 해요?"


RULES: tuple[Callable[[str], str], ...] = (
    p0_suffix_drop, p1_swap, p2_keywords, p3_nospace, p4_casual,
)


def _verbatim(chunk: Chunk) -> str:
    if chunk.origin == "text":
        sentences = split_sentences(chunk.text)
        if sentences:
            return sentences[0]
    return chunk.title.strip()


def _colloquial(verbatim: str, pos: int) -> str:
    for k in range(len(RULES)):
        out = RULES[(pos + k) % len(RULES)](verbatim).strip()
        if out and out != verbatim:
            return out
    return verbatim + " 알려주세요"


def _pick(chunks: list[Chunk], m: int) -> list[Chunk]:
    if len(chunks) <= m:
        return chunks
    return [chunks[i * len(chunks) // m] for i in range(m)]


def make_questions(agent: Agent, n: int = 30) -> list[ScoreQuestion]:
    if n <= 0 or not agent.chunks:
        return []
    ordered = sorted(agent.chunks, key=lambda c: c.chunk_id)
    picked = _pick(ordered, (n + 1) // 2)
    texts: list[tuple[str, Style, str]] = []
    for pos, chunk in enumerate(picked):
        verbatim = _verbatim(chunk)
        texts.append((verbatim, "verbatim", chunk.chunk_id))
        texts.append((_colloquial(verbatim, pos), "colloquial", chunk.chunk_id))
    return [
        ScoreQuestion(qid=f"sq-{i:02d}", text=t, style=s, expected_chunk_id=cid)
        for i, (t, s, cid) in enumerate(texts[:n], start=1)
    ]
