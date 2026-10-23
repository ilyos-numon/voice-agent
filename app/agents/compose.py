"""설정에 따른 답 모양: 피할 주제, 모름 판정, 문장 수·말투, 시스템 프롬프트."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from app.agents.models import AgentSettings
from app.agents.retrieval import MIN_QUERY_COVERAGE, Candidate, query_coverage

UNKNOWN_TEXT = "제가 가진 자료에는 그 내용이 없어 답하기 어렵습니다."
AVOIDED_TEXT = "그 주제는 안내해 드리지 않습니다."
FRIENDLY_PREFIX = "네, "
SENTENCE_LIMIT: dict[str, int] = {"one_sentence": 1, "short": 2, "detailed": 4}

_TONE_DESC = {"friendly": "친절하고 부드러운 존댓말", "concise": "군더더기 없는 간결한 존댓말"}


def _norm(s: str) -> str:
    return "".join(unicodedata.normalize("NFC", s).lower().split())


def matches_avoid(query: str, avoid_topics: Sequence[str]) -> bool:
    q = _norm(query)
    return any(t and t in q for t in (_norm(topic) for topic in avoid_topics))


def is_unknown(
    query: str, candidates: Sequence[Candidate], min_coverage: float = MIN_QUERY_COVERAGE
) -> bool:
    if not candidates:
        return True
    return query_coverage(query, candidates[0].chunk) < min_coverage


def unknown_sentence(settings: AgentSettings) -> str:
    return settings.handoff_message if settings.when_unknown == "handoff" else UNKNOWN_TEXT


def shape_sentences(sentences: Sequence[str], settings: AgentSettings) -> list[str]:
    out = [s for s in sentences if s.strip()][: SENTENCE_LIMIT[settings.answer_length]]
    if settings.tone == "friendly" and out and not out[0].startswith(FRIENDLY_PREFIX):
        out[0] = FRIENDLY_PREFIX + out[0]
    return out


def system_prompt(settings: AgentSettings) -> str:
    n = SENTENCE_LIMIT[settings.answer_length]
    lines = [
        f"당신은 '{settings.persona_name}'이라는 이름의 음성 상담원입니다.",
        f"말투: {_TONE_DESC[settings.tone]}로 답합니다.",
        f"답은 {n}문장 이내로 합니다.",
        "주어진 자료(근거)에 있는 내용만 말하고, 근거 밖의 내용은 지어내지 않습니다(근거 밖 금지).",
        f"자료에 답이 없으면 '{unknown_sentence(settings)}'라고만 말합니다.",
    ]
    if settings.avoid_topics:
        lines.append(f"다음 주제는 안내하지 않습니다(피할 주제): {', '.join(settings.avoid_topics)}.")
    return "\n".join(lines)
