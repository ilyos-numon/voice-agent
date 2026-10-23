"""상담원별 지식 조각 BM25 검색과 질문 bigram 포함률."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.models import Chunk
from app.pipeline.bm25 import BM25Index, tokenize

# design D3 규칙으로 scripts/tune_unknown.py 측정 결과에서 고른 값
MIN_QUERY_COVERAGE: float = 0.20

# 요청·어미 표현의 bigram. 내용어(필요·발급·주차 등)는 넣지 않는다
_GENERIC_PHRASES = (
    "방법", "알려", "알려주세요", "주세요", "어떻게", "하나요", "해요", "돼요",
    "되나요", "되요", "있나요", "인가요", "할까요", "싶어요",
)
GENERIC_BIGRAMS: frozenset[str] = frozenset(t for p in _GENERIC_PHRASES for t in tokenize(p))


@dataclass(frozen=True)
class Candidate:
    chunk: Chunk
    score: float
    rank: int


class ChunkIndex:
    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = tuple(chunks)
        self.index = BM25Index([tokenize(c.index_text) for c in self.chunks])

    def search(self, query: str, top_k: int = 3) -> list[Candidate]:
        hits = self.index.score(tokenize(query))[:top_k]
        return [
            Candidate(chunk=self.chunks[i], score=s, rank=r)
            for r, (i, s) in enumerate(hits, start=1)
        ]


def query_coverage(query: str, chunk: Chunk) -> float:
    q = set(tokenize(query)) - GENERIC_BIGRAMS
    if not q:
        return 0.0
    c = set(tokenize(chunk.title + "\n" + chunk.text)) - GENERIC_BIGRAMS
    return len(q & c) / len(q)
