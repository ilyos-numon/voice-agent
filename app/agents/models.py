"""상담원·설정·지식 조각 도메인 타입."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

AnswerLength = Literal["one_sentence", "short", "detailed"]
Tone = Literal["friendly", "concise"]
WhenUnknown = Literal["say_unknown", "handoff"]
VoiceId = Literal["calm_female", "bright_female", "calm_male", "deep_male"]
AnswerKind = Literal["grounded", "unknown", "avoided"]
ChunkOrigin = Literal["text", "faq_csv", "preset"]

PERSONA_MAX_CHARS = 20
HANDOFF_MAX_CHARS = 100
AVOID_MAX_TOPICS = 10
AVOID_TOPIC_MAX_CHARS = 20


@dataclass(frozen=True)
class AgentSettings:
    persona_name: str = "상담원"
    tone: Tone = "friendly"
    voice: VoiceId = "calm_female"
    answer_length: AnswerLength = "short"
    when_unknown: WhenUnknown = "say_unknown"
    handoff_message: str = "담당자에게 문의해 주세요."
    avoid_topics: tuple[str, ...] = ()
    summary: bool = False


_LITERALS: dict[str, tuple[str, ...]] = {
    "tone": get_args(Tone),
    "voice": get_args(VoiceId),
    "answer_length": get_args(AnswerLength),
    "when_unknown": get_args(WhenUnknown),
}
_FIELDS = {f.name for f in dataclasses.fields(AgentSettings)}


def _text(key: str, value: Any, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key}: 문자열이어야 합니다")  # noqa: TRY004 (계약: ValueError)
    v = value.strip()
    if not 1 <= len(v) <= max_chars:
        raise ValueError(f"{key}: 1~{max_chars}자여야 합니다")
    return v


def _validate(key: str, value: Any) -> Any:
    if key in _LITERALS:
        if not isinstance(value, str) or value not in _LITERALS[key]:
            raise ValueError(f"{key}: 허용되지 않는 값입니다")
        return value
    if key == "persona_name":
        return _text(key, value, PERSONA_MAX_CHARS)
    if key == "handoff_message":
        return _text(key, value, HANDOFF_MAX_CHARS)
    if key == "summary":
        if not isinstance(value, bool):
            raise ValueError("summary: true/false 여야 합니다")
        return value
    # avoid_topics
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("avoid_topics: 목록이어야 합니다")  # noqa: TRY004
    if len(value) > AVOID_MAX_TOPICS:
        raise ValueError(f"avoid_topics: 최대 {AVOID_MAX_TOPICS}개입니다")
    return tuple(_text(key, t, AVOID_TOPIC_MAX_CHARS) for t in value)


def merge_settings(base: AgentSettings, patch: Mapping[str, Any]) -> AgentSettings:
    changes: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in _FIELDS:
            raise ValueError(f"알 수 없는 설정입니다: {key}")
        changes[key] = _validate(key, value)
    return dataclasses.replace(base, **changes)


def settings_to_dict(s: AgentSettings) -> dict[str, Any]:
    d = dataclasses.asdict(s)
    d["avoid_topics"] = list(s.avoid_topics)
    return d


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    title: str
    text: str
    index_text: str
    origin: ChunkOrigin


@dataclass(frozen=True)
class Agent:
    agent_id: str
    name: str
    preset_id: str | None
    settings: AgentSettings
    chunks: tuple[Chunk, ...]
    created_at: float
    expires_at: float | None
