"""빌더 API 요청·응답 스키마 (PLAN §4.3·§4.4 계약)."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.models import (
    AVOID_MAX_TOPICS,
    AgentSettings,
    AnswerKind,
    AnswerLength,
    Tone,
    VoiceId,
    WhenUnknown,
    merge_settings,
)

MAX_QUESTION_CHARS = 500
MAX_AGENT_NAME_CHARS = 30
DEFAULT_AGENT_NAME = "내 상담원"


def _not_blank(v: str) -> str:
    stripped = v.strip()
    if not stripped:
        raise ValueError("빈 문자열은 안 됩니다")
    return stripped


# ---- 설정 ----


class SettingsOut(BaseModel):
    persona_name: str
    tone: Tone
    voice: VoiceId
    answer_length: AnswerLength
    when_unknown: WhenUnknown
    handoff_message: str
    avoid_topics: list[str]
    summary: bool


class _SettingsFields(BaseModel):
    persona_name: str | None = None
    tone: Tone | None = None
    voice: VoiceId | None = None
    answer_length: AnswerLength | None = None
    when_unknown: WhenUnknown | None = None
    handoff_message: str | None = None
    avoid_topics: list[str] | None = Field(default=None, max_length=AVOID_MAX_TOPICS)
    summary: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> "_SettingsFields":
        merge_settings(AgentSettings(), self.patch())  # ValueError → 422
        return self

    def patch(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class SettingsIn(_SettingsFields):
    pass


class SettingsPatch(_SettingsFields):
    model_config = ConfigDict(extra="forbid")


# ---- 상담원 ----


class TextKnowledge(BaseModel):
    kind: Literal["text"]
    text: str


class CsvKnowledge(BaseModel):
    kind: Literal["faq_csv"]
    csv: str


Knowledge = Annotated[TextKnowledge | CsvKnowledge, Field(discriminator="kind")]


class CreateAgentIn(BaseModel):
    name: str = Field(default=DEFAULT_AGENT_NAME, min_length=1, max_length=MAX_AGENT_NAME_CHARS)
    knowledge: Knowledge
    settings: SettingsIn = Field(default_factory=SettingsIn)

    _name = field_validator("name")(_not_blank)


class WarningOut(BaseModel):
    code: str
    message: str


class AgentOut(BaseModel):
    agent_id: str
    name: str
    preset_id: str | None
    settings: SettingsOut
    chunk_count: int
    created_at: str
    expires_at: str | None
    share_path: str
    warnings: list[WarningOut]


class PresetOut(BaseModel):
    preset_id: str
    title: str
    description: str
    sample_questions: list[str]
    agent_id: str
    chunk_count: int


class PresetsOut(BaseModel):
    items: list[PresetOut]


class ChunkOut(BaseModel):
    chunk_id: str
    title: str
    text: str


class ChunksOut(BaseModel):
    total: int
    items: list[ChunkOut]


class SessionOut(BaseModel):
    session_id: str
    agent_id: str
    questions_left: int
    expires_at: str


# ---- 선택지 ----


class OptionOut(BaseModel):
    value: str
    label: str


class VoiceOptionOut(OptionOut):
    available: bool


class LimitsOut(BaseModel):
    max_text_chars: int
    max_csv_rows: int
    max_csv_chars: int
    max_questions_per_session: int
    agent_ttl_hours: float
    max_avoid_topics: int
    max_avoid_topic_chars: int
    max_persona_name_chars: int
    max_handoff_message_chars: int
    max_question_chars: int


class OptionsOut(BaseModel):
    answer_length: list[OptionOut]
    tone: list[OptionOut]
    when_unknown: list[OptionOut]
    voices: list[VoiceOptionOut]
    defaults: SettingsOut
    limits: LimitsOut
    summary_available: bool
    voice_input_available: bool


# ---- 턴 ----


class TurnIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    _text = field_validator("text")(_not_blank)


class CandidateOut(BaseModel):
    rank: int
    chunk_id: str
    title: str
    score: float


class EvidenceOut(BaseModel):
    chunk_id: str
    title: str
    quote: str
    overlap: float


class QueueEventOut(BaseModel):
    position: int


class MetaTimingsOut(BaseModel):
    listen_ms: float
    search_ms: float
    think_ms: float


class TurnMetaOut(BaseModel):
    turn_id: str
    transcript: str
    answer_kind: AnswerKind
    sentence_count: int
    candidates: list[CandidateOut]
    timings: MetaTimingsOut


class TurnSentenceOut(BaseModel):
    index: int
    text: str
    supported: bool
    evidence: list[EvidenceOut]
    audio_wav_b64: str
    speak_ms: float
    elapsed_ms: float


class DoneTimingsOut(MetaTimingsOut):
    speak_ms: float
    first_audio_ms: float
    total_ms: float
    queue_ms: float


class TurnDoneOut(BaseModel):
    turn_id: str
    sentence_count: int
    answer_kind: AnswerKind
    summary_used: bool
    questions_left: int
    timings: DoneTimingsOut


class TurnErrorOut(BaseModel):
    code: Literal["no_speech", "audio_decode_failed", "internal"]
    message: str


# ---- A/B 비교 ----


class CompareIn(BaseModel):
    session_id: str
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    a: SettingsPatch = Field(default_factory=SettingsPatch)
    b: SettingsPatch = Field(default_factory=SettingsPatch)

    _question = field_validator("question")(_not_blank)


class SideSentenceOut(BaseModel):
    index: int
    text: str
    supported: bool
    evidence: list[EvidenceOut]
    audio_wav_b64: str
    speak_ms: float


class SideTimingsOut(MetaTimingsOut):
    speak_ms: float
    first_audio_ms: float
    total_ms: float


class SideOut(BaseModel):
    settings: SettingsOut
    answer_kind: AnswerKind
    answer: str
    sentence_count: int
    char_count: int
    summary_used: bool
    candidates: list[CandidateOut]
    sentences: list[SideSentenceOut]
    timings: SideTimingsOut


class DiffOut(BaseModel):
    first_audio_ms: float
    sentence_count: int
    char_count: int


class CompareOut(BaseModel):
    question: str
    a: SideOut
    b: SideOut
    diff: DiffOut
    notes: list[str]
    questions_left: int


# ---- 성적표 ----


class ScorecardIn(BaseModel):
    n: int = Field(default=30, ge=10, le=30)
    voice: bool = True


class ScorecardAccepted(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    position: int


class HitsOut(BaseModel):
    hits: int
    total: int


class ByStyleOut(BaseModel):
    verbatim: HitsOut
    colloquial: HitsOut


class PercentilesOut(BaseModel):
    p50: float
    p95: float


class ChunkRefOut(BaseModel):
    chunk_id: str
    title: str


class FailureOut(BaseModel):
    qid: str
    question: str
    style: Literal["verbatim", "colloquial"]
    channel: Literal["text", "voice"]
    expected: ChunkRefOut
    got: ChunkRefOut | None
    heard: str | None
    reason: Literal["wrong_chunk", "no_answer", "misheard"]


class HintOut(BaseModel):
    code: Literal["similar_chunks", "misheard", "long_chunks", "colloquial_gap"]
    message: str
    chunk_ids: list[str]


class ReportOut(BaseModel):
    agent_id: str
    question_count: int
    generated_by: Literal["rules"]
    caveat: str
    text: HitsOut
    voice: HitsOut | None
    voice_unavailable_reason: Literal["stub_audio"] | None
    by_style: ByStyleOut
    first_audio_ms: PercentilesOut
    first_audio_basis: Literal["voice", "text"]
    failures: list[FailureOut]
    hints: list[HintOut]


class ProgressOut(BaseModel):
    done: int
    total: int


class JobErrorOut(BaseModel):
    code: str
    message: str


class JobOut(BaseModel):
    job_id: str
    agent_id: str
    status: Literal["queued", "running", "done", "failed"]
    progress: ProgressOut
    report: ReportOut | None
    error: JobErrorOut | None
