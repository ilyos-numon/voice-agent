"""답 문장마다 지식 조각 근거를 bigram 겹침으로 붙인다."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.agents.retrieval import Candidate
from app.pipeline.bm25 import tokenize
from app.pipeline.sentences import split_sentences

GROUNDING_MIN_OVERLAP = 0.5
_TONE_PREFIX = "네, "


@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    title: str
    quote: str
    overlap: float


@dataclass(frozen=True)
class GroundedSentence:
    index: int
    text: str
    supported: bool
    evidence: tuple[Evidence, ...]


def _overlap(sent: set[str], text: str) -> float:
    return len(sent & set(tokenize(text))) / len(sent)


def _quote(sent: set[str], cand: Candidate) -> str:
    parts = split_sentences(cand.chunk.text) or [cand.chunk.title]
    return max(parts, key=lambda p: _overlap(sent, p))


def ground_sentences(
    sentences: Sequence[str],
    candidates: Sequence[Candidate],
    min_overlap: float = GROUNDING_MIN_OVERLAP,
) -> list[GroundedSentence]:
    out: list[GroundedSentence] = []
    for i, text in enumerate(sentences):
        body = text.removeprefix(_TONE_PREFIX)
        sent = set(tokenize(body))
        evidence: list[Evidence] = []
        if sent:
            for cand in candidates:
                ov = _overlap(sent, cand.chunk.text + "\n" + cand.chunk.title)
                if ov >= min_overlap:
                    evidence.append(
                        Evidence(
                            chunk_id=cand.chunk.chunk_id,
                            title=cand.chunk.title,
                            quote=_quote(sent, cand),
                            overlap=round(ov, 3),
                        )
                    )
        evidence.sort(key=lambda e: -e.overlap)
        out.append(GroundedSentence(index=i, text=text, supported=bool(evidence), evidence=tuple(evidence)))
    return out
