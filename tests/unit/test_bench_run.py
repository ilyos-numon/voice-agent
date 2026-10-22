import base64
import importlib
import io
import sys
import wave
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2] / "bench"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))
run = importlib.import_module("run")

Q = {"id": "faq-001", "query": "질문", "answer_chars": 46}


def _wav_b64(seconds: float, rate: int = 16000) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ask_resp(source_id: str | None = "faq-001") -> dict:
    return {
        "transcript": "질문",
        "answer": "답",
        "source": None if source_id is None else {"id": source_id, "question": "q", "source": "s"},
        "timings": {"stt_ms": 0.1, "retrieve_ms": 0.3, "llm_ms": 0.0, "tts_ms": 100.04, "total_ms": 101.26},
        "audio_wav_b64": _wav_b64(0.5),
    }


def _stream_events(source_id: str | None = "faq-001") -> list:
    src = None if source_id is None else {"id": source_id, "question": "q", "source": "s"}
    return [
        ("meta", {"transcript": "t", "answer": "a", "source": src, "sentence_count": 2, "timings": {}}),
        ("audio", {"index": 0, "text": "a", "audio_wav_b64": _wav_b64(0.5), "tts_ms": 10, "elapsed_ms": 20}),
        ("audio", {"index": 1, "text": "b", "audio_wav_b64": _wav_b64(0.25), "tts_ms": 10, "elapsed_ms": 30}),
        (
            "done",
            {
                "sentence_count": 2,
                "timings": {
                    "stt_ms": 0.0, "retrieve_ms": 1.0, "llm_ms": 0.0, "tts_ms": 20.0,
                    "total_ms": 31.0, "first_audio_ms": 21.0,
                },
            },
        ),
    ]


def test_parse_sse_order_and_ignores_lines_without_data() -> None:
    lines = [
        "event: meta", 'data: {"a": 1}', "",
        ": comment", "data: {\"orphan\": true}",
        "event: audio", 'data: {"b": 2}', "",
        "event: done", 'data: {"c": 3}', "",
    ]
    assert run.parse_sse(lines) == [("meta", {"a": 1}), ("audio", {"b": 2}), ("done", {"c": 3})]


def test_record_from_ask_first_audio_equals_total_and_stage_keys() -> None:
    rec = run.record_from_ask("before", 1, Q, _ask_resp(), 120.04)
    assert rec["first_audio_ms"] == rec["total_ms"] == 101.3
    assert set(rec["stages"]) == {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms"}
    assert rec["client_first_audio_ms"] == rec["client_total_ms"] == 120.0
    assert rec["sentence_count"] is None
    assert rec["hit"] is True and rec["status"] == "ok" and rec["error"] is None
    assert abs(rec["audio_s"] - 0.5) < 1e-6


def test_record_from_stream_excludes_total_and_first_audio_from_stages() -> None:
    rec = run.record_from_stream("after", 1, Q, _stream_events(), 25.0, 40.0)
    assert set(rec["stages"]) == {"stt_ms", "retrieve_ms", "llm_ms", "tts_ms"}
    assert rec["total_ms"] == 31.0 and rec["first_audio_ms"] == 21.0
    assert rec["sentence_count"] == 2
    assert rec["client_first_audio_ms"] == 25.0 and rec["client_total_ms"] == 40.0
    assert abs(rec["audio_s"] - 0.75) < 1e-6
    assert rec["hit"] is True and rec["status"] == "ok"


def test_record_from_stream_error_event_sets_status_error() -> None:
    events = [("error", {"detail": "internal error"})]
    rec = run.record_from_stream("after", 1, Q, events, None, 5.0)
    assert rec["status"] == "error"
    assert rec["error"] == "internal error"
    assert rec["total_ms"] is None and rec["first_audio_ms"] is None


def test_hit_false_when_source_null() -> None:
    assert run.record_from_ask("before", 1, Q, _ask_resp(None), 1.0)["hit"] is False
    assert run.record_from_stream("after", 1, Q, _stream_events(None), 1.0, 2.0)["hit"] is False


def test_hit_false_when_source_differs() -> None:
    assert run.record_from_ask("before", 1, Q, _ask_resp("faq-999"), 1.0)["hit"] is False


def test_configs_registry() -> None:
    assert run.CONFIGS["before"]["endpoint"] == "/api/ask"
    assert run.CONFIGS["after"]["endpoint"] == "/api/ask-stream"


def test_unreachable_server_yields_error_record() -> None:
    rec = run.run_one("before", 1, Q, "http://localhost:1", 2.0)
    assert rec["status"] == "error" and rec["total_ms"] is None and rec["error"]
