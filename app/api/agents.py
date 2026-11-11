"""상담원 빌더 API (PLAN §4.3 REST, §4.4 SSE). 상태는 app.state.agents / app.state.scorecard_jobs."""

import base64
import logging
import math
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.agents.compare import compare_settings
from app.agents.jobs import Job, JobBusy, JobRunning, ScorecardJobs
from app.agents.knowledge import KnowledgeError, KnowledgeWarning, chunk_text, parse_faq_csv
from app.agents.limits import Busy, QuestionLimit, SessionNotFound, Ticket
from app.agents.models import (
    AVOID_MAX_TOPICS,
    AVOID_TOPIC_MAX_CHARS,
    HANDOFF_MAX_CHARS,
    PERSONA_MAX_CHARS,
    Agent,
    AgentSettings,
    merge_settings,
    settings_to_dict,
)
from app.agents.retrieval import Candidate
from app.agents.runtime import AgentRuntime
from app.agents.store import AgentNotFound, CapacityFull, PresetReadOnly
from app.agents.turn import TurnMeta, TurnSentence, iter_turn
from app.api.agent_schemas import (
    MAX_QUESTION_CHARS,
    AgentOut,
    CandidateOut,
    ChunkOut,
    ChunksOut,
    CompareIn,
    CompareOut,
    CreateAgentIn,
    DoneTimingsOut,
    EvidenceOut,
    JobOut,
    LimitsOut,
    MetaTimingsOut,
    OptionOut,
    OptionsOut,
    PresetOut,
    PresetsOut,
    ProgressOut,
    QueueEventOut,
    ScorecardAccepted,
    ScorecardIn,
    SessionOut,
    SettingsOut,
    SettingsPatch,
    TextKnowledge,
    TurnDoneOut,
    TurnErrorOut,
    TurnIn,
    TurnMetaOut,
    TurnSentenceOut,
    VoiceOptionOut,
    WarningOut,
)
from app.api.stream import SSE_HEADERS, format_sse
from app.config import get_settings
from app.demo.quota import Kind, charge_request, refund_request, request_bucket
from app.pipeline.audio import (
    MAX_AUDIO_BYTES,
    AudioDecodeError,
    NoSpeechError,
    decode_audio,
    sniff_format,
)
from app.pipeline.stubs import PassthroughSTT

logger = logging.getLogger(__name__)

agents_router = APIRouter()

QUEUE_TICK_S = 1.0
SHARE_PATH = "/talk?agent="

ANSWER_LENGTH_LABELS = [("one_sentence", "한 문장"), ("short", "짧게"), ("detailed", "자세히")]
TONE_LABELS = [("friendly", "친절하게"), ("concise", "간결하게")]
WHEN_UNKNOWN_LABELS = [("say_unknown", "모른다고 말하기"), ("handoff", "담당자 안내 문구")]
VOICE_LABELS = [
    ("calm_female", "차분한 여성"),
    ("bright_female", "밝은 여성"),
    ("calm_male", "차분한 남성"),
    ("deep_male", "낮은 남성"),
]


# ---- 공통 ----


def _rt(request: Request) -> AgentRuntime:
    rt: AgentRuntime = request.app.state.agents
    return rt


def _jobs(request: Request) -> ScorecardJobs:
    jobs: ScorecardJobs = request.app.state.scorecard_jobs
    return jobs


def _fail(status: int, code: str, message: str, **extra: str) -> NoReturn:
    raise HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r1(timings: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 1) for k, v in timings.items()}


def _get_agent(rt: AgentRuntime, agent_id: str) -> Agent:
    try:
        return rt.store.get(agent_id)
    except AgentNotFound:
        _fail(404, "agent_not_found", "상담원을 찾을 수 없습니다.")


def _base_settings() -> AgentSettings:
    return AgentSettings(summary=get_settings().agent_summary_default)


def _settings_out(s: AgentSettings) -> SettingsOut:
    return SettingsOut(**settings_to_dict(s))


def _agent_out(agent: Agent, warnings: list[KnowledgeWarning] | None = None) -> AgentOut:
    return AgentOut(
        agent_id=agent.agent_id,
        name=agent.name,
        preset_id=agent.preset_id,
        settings=_settings_out(agent.settings),
        chunk_count=len(agent.chunks),
        created_at=_iso(agent.created_at),
        expires_at=_iso(agent.expires_at) if agent.expires_at is not None else None,
        share_path=SHARE_PATH + agent.agent_id,
        warnings=[WarningOut(code=w.code, message=w.message) for w in warnings or []],
    )


def _candidate_out(c: Candidate) -> CandidateOut:
    return CandidateOut(rank=c.rank, chunk_id=c.chunk.chunk_id, title=c.chunk.title, score=round(c.score, 2))


def _consume(rt: AgentRuntime, session_id: str, agent_id: str) -> int:
    try:
        return rt.sessions.consume(session_id, agent_id)
    except SessionNotFound:
        _fail(404, "session_not_found", "대화 세션을 찾을 수 없습니다. 새 세션을 열어 주세요.")
    except QuestionLimit:
        _fail(429, "question_limit", "이 세션의 질문 수를 다 썼습니다.")


def _busy() -> NoReturn:
    _fail(503, "busy", "지금 요청이 많습니다. 잠시 뒤 다시 시도해 주세요.")


# ---- 데모 한도 (app.state.demo_quota 가 None 이면 아무것도 안 함) ----

Charges = tuple[tuple[Kind, int], ...]


def _charge(request: Request, charges: Charges) -> None:
    done: list[tuple[Kind, int]] = []
    try:
        for kind, amount in charges:
            charge_request(request, kind, amount)
            done.append((kind, amount))
    except HTTPException:
        _refund(request, tuple(done))
        raise


def _refund(request: Request, charges: Charges) -> None:
    for kind, amount in charges:
        refund_request(request, kind, amount)


def _audio_seconds(body: bytes) -> int | None:
    try:
        pcm = decode_audio(body)
    except ImportError:
        return math.ceil(len(body) / 32000)
    except AudioDecodeError:
        return None
    return math.ceil(len(pcm) / 16000)


async def _audio_charges(request: Request, body: bytes) -> Charges:
    if request_bucket(request) is None:
        return ()
    seconds = await run_in_threadpool(_audio_seconds, body)
    if seconds is None:
        return (("turns", 1),)
    max_seconds = int(getattr(request.app.state.demo_settings, "demo_max_audio_seconds_per_turn", 0))
    if seconds > max_seconds:
        _fail(413, "audio_too_large", "녹음이 너무 깁니다.")
    return (("audio_seconds", seconds), ("turns", 1))


# ---- 선택지·프리셋 ----


@agents_router.get("/api/options", response_model=OptionsOut)
def get_options(request: Request) -> OptionsOut:
    rt = _rt(request)
    lim = rt.limits
    return OptionsOut(
        answer_length=[OptionOut(value=v, label=lb) for v, lb in ANSWER_LENGTH_LABELS],
        tone=[OptionOut(value=v, label=lb) for v, lb in TONE_LABELS],
        when_unknown=[OptionOut(value=v, label=lb) for v, lb in WHEN_UNKNOWN_LABELS],
        voices=[
            VoiceOptionOut(value=v, label=lb, available=rt.voice_available(v)) for v, lb in VOICE_LABELS
        ],
        defaults=_settings_out(_base_settings()),
        limits=LimitsOut(
            max_text_chars=lim.max_text_chars,
            max_csv_rows=lim.max_csv_rows,
            max_csv_chars=lim.max_csv_chars,
            max_questions_per_session=lim.session_max_questions,
            agent_ttl_hours=lim.agent_ttl_hours,
            max_avoid_topics=AVOID_MAX_TOPICS,
            max_avoid_topic_chars=AVOID_TOPIC_MAX_CHARS,
            max_persona_name_chars=PERSONA_MAX_CHARS,
            max_handoff_message_chars=HANDOFF_MAX_CHARS,
            max_question_chars=MAX_QUESTION_CHARS,
        ),
        summary_available=rt.llm_factory is not None,
        voice_input_available=not isinstance(rt.stt, PassthroughSTT),
    )


@agents_router.get("/api/presets", response_model=PresetsOut)
def get_presets(request: Request) -> PresetsOut:
    return PresetsOut(
        items=[
            PresetOut(
                preset_id=p.preset_id,
                title=p.title,
                description=p.description,
                sample_questions=list(p.sample_questions),
                agent_id=p.agent.agent_id,
                chunk_count=len(p.agent.chunks),
            )
            for p in _rt(request).presets
        ]
    )


# ---- 상담원 ----


@agents_router.post("/api/agents", status_code=201, response_model=AgentOut)
def create_agent(body: CreateAgentIn, request: Request) -> AgentOut:
    rt = _rt(request)
    charges: Charges = (("agents", 1),)
    _charge(request, charges)
    try:
        return _create_agent(rt, body)
    except Exception:
        _refund(request, charges)
        raise


def _create_agent(rt: AgentRuntime, body: CreateAgentIn) -> AgentOut:
    lim = rt.limits
    kn = body.knowledge
    try:
        if isinstance(kn, TextKnowledge):
            chunks, warnings = chunk_text(kn.text, lim.max_text_chars)
        else:
            chunks, warnings = parse_faq_csv(kn.csv, lim.max_csv_rows, lim.max_csv_chars)
    except KnowledgeError as e:
        _fail(413 if e.code == "knowledge_too_large" else 400, e.code, e.message)
    settings = merge_settings(_base_settings(), body.settings.patch())
    try:
        agent = rt.store.create(body.name, settings, tuple(chunks))
    except CapacityFull:
        _fail(503, "capacity_full", "지금은 상담원을 더 만들 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
    return _agent_out(agent, warnings)


@agents_router.get("/api/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, request: Request) -> AgentOut:
    return _agent_out(_get_agent(_rt(request), agent_id))


@agents_router.patch("/api/agents/{agent_id}/settings", response_model=AgentOut)
def patch_settings(agent_id: str, body: SettingsPatch, request: Request) -> AgentOut:
    rt = _rt(request)
    agent = _get_agent(rt, agent_id)
    settings = merge_settings(agent.settings, body.patch())
    try:
        updated = rt.store.update_settings(agent_id, settings)
    except PresetReadOnly:
        _fail(403, "preset_read_only", "프리셋 상담원은 바꿀 수 없습니다.")
    except AgentNotFound:
        _fail(404, "agent_not_found", "상담원을 찾을 수 없습니다.")
    return _agent_out(updated)


@agents_router.delete("/api/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: str, request: Request) -> Response:
    rt = _rt(request)
    _get_agent(rt, agent_id)
    try:
        rt.store.delete(agent_id)
    except PresetReadOnly:
        _fail(403, "preset_read_only", "프리셋 상담원은 지울 수 없습니다.")
    except AgentNotFound:
        _fail(404, "agent_not_found", "상담원을 찾을 수 없습니다.")
    return Response(status_code=204)


@agents_router.get("/api/agents/{agent_id}/chunks", response_model=ChunksOut)
def get_chunks(
    agent_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ChunksOut:
    agent = _get_agent(_rt(request), agent_id)
    page = agent.chunks[offset : offset + limit]
    return ChunksOut(
        total=len(agent.chunks),
        items=[ChunkOut(chunk_id=c.chunk_id, title=c.title, text=c.text) for c in page],
    )


@agents_router.post("/api/agents/{agent_id}/sessions", status_code=201, response_model=SessionOut)
def open_session(agent_id: str, request: Request) -> SessionOut:
    rt = _rt(request)
    agent = _get_agent(rt, agent_id)
    s = rt.sessions.open(agent.agent_id)
    return SessionOut(
        session_id=s.session_id,
        agent_id=s.agent_id,
        questions_left=s.max_questions - s.used,
        expires_at=_iso(s.expires_at),
    )


# ---- 턴 (SSE) ----


def _sse(name: str, data: BaseModel) -> bytes:
    return format_sse(name, data)


def _turn_events(
    rt: AgentRuntime, agent: Agent, ticket: Ticket, questions_left: int, *,
    text: str | None = None, audio: bytes | None = None,
) -> Iterator[bytes]:
    try:
        t_wait = time.perf_counter()
        position = ticket.position()
        if position > 0:
            yield _sse("queue", QueueEventOut(position=position))
            while not ticket.wait(QUEUE_TICK_S):
                position = ticket.position()
                if position > 0:
                    yield _sse("queue", QueueEventOut(position=position))
        queue_ms = (time.perf_counter() - t_wait) * 1000
        for ev in iter_turn(rt, agent, text=text, audio=audio):
            if isinstance(ev, TurnMeta):
                yield _sse(
                    "meta",
                    TurnMetaOut(
                        turn_id=ev.turn_id,
                        transcript=ev.transcript,
                        answer_kind=ev.answer_kind,
                        sentence_count=ev.sentence_count,
                        candidates=[_candidate_out(c) for c in ev.candidates[:3]],
                        timings=MetaTimingsOut(**_r1(ev.timings)),
                    ),
                )
            elif isinstance(ev, TurnSentence):
                yield _sse(
                    "sentence",
                    TurnSentenceOut(
                        index=ev.index,
                        text=ev.text,
                        supported=ev.supported,
                        evidence=[
                            EvidenceOut(chunk_id=e.chunk_id, title=e.title, quote=e.quote, overlap=e.overlap)
                            for e in ev.evidence
                        ],
                        audio_wav_b64=base64.b64encode(ev.audio_wav).decode("ascii"),
                        speak_ms=round(ev.speak_ms, 1),
                        elapsed_ms=round(ev.elapsed_ms, 1),
                    ),
                )
            else:
                yield _sse(
                    "done",
                    TurnDoneOut(
                        turn_id=ev.turn_id,
                        sentence_count=ev.sentence_count,
                        answer_kind=ev.answer_kind,
                        summary_used=ev.summary_used,
                        questions_left=questions_left,
                        timings=DoneTimingsOut(**_r1({**ev.timings, "queue_ms": queue_ms})),
                    ),
                )
    except AudioDecodeError:
        yield _sse("error", TurnErrorOut(code="audio_decode_failed", message="음성을 읽을 수 없습니다."))
    except NoSpeechError:
        yield _sse("error", TurnErrorOut(code="no_speech", message="말소리를 알아듣지 못했습니다."))
    except Exception:
        logger.exception("agent turn stream failed")
        yield _sse("error", TurnErrorOut(code="internal", message="답을 만드는 중 오류가 났습니다."))
    finally:
        ticket.release()


def _start_turn(
    rt: AgentRuntime, agent: Agent, session_id: str, *, text: str | None = None, audio: bytes | None = None
) -> StreamingResponse:
    questions_left = _consume(rt, session_id, agent.agent_id)
    try:
        ticket = rt.gate.enter()
    except Busy:
        rt.sessions.refund(session_id)
        _busy()
    gen = _turn_events(rt, agent, ticket, questions_left, text=text, audio=audio)
    # 스트림이 시작되지 않고 끝나도 슬롯을 돌려준다 (release는 여러 번 불러도 안전)
    return StreamingResponse(
        gen, media_type="text/event-stream", headers=SSE_HEADERS, background=BackgroundTask(ticket.release)
    )


@agents_router.post("/api/agents/{agent_id}/turns/stream")
def turn_stream(agent_id: str, body: TurnIn, request: Request) -> StreamingResponse:
    rt = _rt(request)
    agent = _get_agent(rt, agent_id)
    charges: Charges = (("turns", 1),)
    _charge(request, charges)
    try:
        return _start_turn(rt, agent, body.session_id, text=body.text)
    except HTTPException:
        _refund(request, charges)
        raise


@agents_router.post("/api/agents/{agent_id}/turns/audio-stream")
async def turn_audio_stream(
    agent_id: str, request: Request, session_id: str = Query(min_length=1)
) -> StreamingResponse:
    rt = _rt(request)
    agent = _get_agent(rt, agent_id)
    body = await request.body()
    if len(body) == 0:
        _fail(400, "empty_audio", "녹음된 소리가 없습니다.")
    if len(body) > MAX_AUDIO_BYTES:
        _fail(413, "audio_too_large", "녹음이 너무 깁니다.")
    if sniff_format(body) is None:
        _fail(415, "unsupported_audio", "지원하지 않는 녹음 형식입니다.")
    charges = await _audio_charges(request, body)
    _charge(request, charges)
    try:
        return _start_turn(rt, agent, session_id, audio=body)
    except HTTPException:
        _refund(request, charges)
        raise


# ---- A/B 비교 ----


@agents_router.post("/api/agents/{agent_id}/compare", response_model=CompareOut)
async def compare(agent_id: str, body: CompareIn, request: Request) -> CompareOut:
    rt = _rt(request)
    agent = _get_agent(rt, agent_id)
    charges: Charges = (("turns", 2),)
    _charge(request, charges)
    try:
        questions_left = _consume(rt, body.session_id, agent.agent_id)
        try:
            result: dict[str, Any] = await run_in_threadpool(
                compare_settings, rt, agent, body.question, body.a.patch(), body.b.patch()
            )
        except Busy:
            rt.sessions.refund(body.session_id)
            _busy()
    except HTTPException:
        _refund(request, charges)
        raise
    return CompareOut(**result, questions_left=questions_left)


# ---- 성적표 ----


def _job_out(job: Job) -> JobOut:
    return JobOut.model_validate(
        {
            "job_id": job.job_id,
            "agent_id": job.agent_id,
            "status": job.status,
            "progress": ProgressOut(done=job.done, total=job.total),
            "report": job.report,
            "error": job.error,
        }
    )


@agents_router.post("/api/agents/{agent_id}/scorecards", status_code=202, response_model=ScorecardAccepted)
def submit_scorecard(agent_id: str, request: Request, body: ScorecardIn | None = None) -> ScorecardAccepted:
    rt = _rt(request)
    jobs = _jobs(request)
    charges: Charges = (("scorecards", 1),)
    _charge(request, charges)
    try:
        agent = _get_agent(rt, agent_id)
        req = body if body is not None else ScorecardIn()
        try:
            job = jobs.submit(agent, req.n, req.voice)
        except JobRunning as e:
            _fail(409, "scorecard_running", "이 상담원의 성적표를 이미 만들고 있습니다.", job_id=e.job_id)
        except JobBusy:
            _busy()
    except HTTPException:
        _refund(request, charges)
        raise
    return ScorecardAccepted(job_id=job.job_id, status=job.status, position=jobs.position(job.job_id))


@agents_router.get("/api/scorecards/{job_id}", response_model=JobOut)
def get_scorecard(job_id: str, request: Request) -> JobOut:
    try:
        job = _jobs(request).get(job_id)
    except KeyError:
        _fail(404, "job_not_found", "성적표 작업을 찾을 수 없습니다.")
    return _job_out(job)
