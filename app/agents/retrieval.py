"""상담원별 지식 조각 BM25 검색과 질문 bigram 포함률."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.models import Chunk
from app.pipeline.bm25 import BM25Index

# design D3 규칙으로 scripts/tune_unknown.py 측정 결과에서 고른 값
MIN_QUERY_COVERAGE: float = 0.20

_WORD_RE = re.compile(r"[0-9a-z가-힣]+")

# 낱말 끝 조사. 긴 것부터 비교한다 (같은 길이는 나열 순서)
# "가"는 restaurant 성적표 sq-20("채식 메뉴가 …")이 떨어져 뺐다 (PLAN §5 Stage 2 실패 시 절차)
_PARTICLES_ORDERED = (
    "에서도", "에서는", "에게는", "으로는", "에서", "에게", "으로", "까지", "부터", "에도", "에는", "이랑",
    "하고", "처럼", "보다", "은", "는", "이", "을", "를", "에", "도", "의", "와", "과", "로", "만",
)
PARTICLES: tuple[str, ...] = tuple(sorted(_PARTICLES_ORDERED, key=len, reverse=True))


def _strip_particle(w: str) -> str:
    for p in PARTICLES:
        if w.endswith(p) and len(w) - len(p) >= 2:
            return w[: -len(p)]
    return w


def agent_tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text):
        w = _strip_particle(raw)
        if len(w) == 1:
            tokens.append(w)
        else:
            tokens.extend(w[i : i + 2] for i in range(len(w) - 1))
    return tokens


# 요청·어미 표현의 bigram. 내용어(필요·발급·주차 등)는 넣지 않는다
_GENERIC_PHRASES = (
    "방법", "알려", "알려주세요", "주세요", "어떻게", "하나요", "해요", "돼요",
    "되나요", "되요", "있나요", "인가요", "할까요", "싶어요", "있어요",
)
GENERIC_BIGRAMS: frozenset[str] = frozenset(t for p in _GENERIC_PHRASES for t in agent_tokenize(p))


def content_tokens(text: str) -> set[str]:
    return set(agent_tokenize(text)) - GENERIC_BIGRAMS


@dataclass(frozen=True)
class Candidate:
    chunk: Chunk
    score: float
    rank: int


class ChunkIndex:
    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = tuple(chunks)
        self.index = BM25Index([agent_tokenize(c.index_text) for c in self.chunks])

    def search(self, query: str, top_k: int = 3) -> list[Candidate]:
        hits = self.index.score(agent_tokenize(query))[:top_k]
        return [
            Candidate(chunk=self.chunks[i], score=s, rank=r)
            for r, (i, s) in enumerate(hits, start=1)
        ]


def query_coverage(query: str, chunk: Chunk) -> float:
    q = content_tokens(query)
    if not q:
        return 0.0
    c = content_tokens(chunk.title + "\n" + chunk.text)
    return len(q & c) / len(q)
