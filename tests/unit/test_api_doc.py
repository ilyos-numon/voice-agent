"""docs/api.md 드리프트 검사: 실제 라우트·SSE 이벤트·오류 code가 문서에 모두 있는지 본다."""

from pathlib import Path

import pytest

from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "api.md"
PREFIXES = ("/api/agents", "/api/presets", "/api/options", "/api/scorecards", "/api/demo")
SSE_EVENTS = ("queue", "meta", "sentence", "done", "error")
ERROR_CODES = (
    "knowledge_empty",
    "knowledge_bad_csv",
    "knowledge_too_large",
    "capacity_full",
    "agent_not_found",
    "preset_read_only",
    "session_not_found",
    "question_limit",
    "busy",
    "empty_audio",
    "audio_too_large",
    "unsupported_audio",
    "scorecard_running",
    "job_not_found",
    "demo_quota_exceeded",
    "demo_daily_cap",
    "rate_limited",
    "payload_too_large",
    "demo_token_required",
    "automated_client",
    "temporarily_blocked",
    "crawler_blocked",
)


def builder_routes() -> list[tuple[str, str]]:
    paths = create_app().openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, ops in paths.items()
        if path.startswith(PREFIXES)
        for method in ops
    )


def route_token(method: str, path: str) -> str:
    return f"`{method} {path}`"


def sse_present(doc: str, name: str) -> bool:
    return f"`event: {name}`" in doc or f"| `{name}` |" in doc


def missing_items(doc: str) -> list[str]:
    missing = [route_token(m, p) for m, p in builder_routes() if route_token(m, p) not in doc]
    missing += [f"event:{e}" for e in SSE_EVENTS if not sse_present(doc, e)]
    missing += [f"code:{c}" for c in ERROR_CODES if f"`{c}`" not in doc]
    return missing


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_builder_routes_found() -> None:
    routes = builder_routes()
    # 라우트 목록이 비면 아래 검사가 공허하게 통과하므로 개수를 고정한다
    assert len(routes) == 14, routes


def test_every_route_documented(doc: str) -> None:
    missing = [route_token(m, p) for m, p in builder_routes() if route_token(m, p) not in doc]
    assert missing == []


def test_every_sse_event_documented(doc: str) -> None:
    assert [e for e in SSE_EVENTS if not sse_present(doc, e)] == []


def test_every_error_code_documented(doc: str) -> None:
    assert len(ERROR_CODES) == 22
    assert [c for c in ERROR_CODES if f"`{c}`" not in doc] == []


def test_doc_complete(doc: str) -> None:
    assert missing_items(doc) == []


def test_checker_catches_deleted_route_line(doc: str) -> None:
    method, path = builder_routes()[0]
    token = route_token(method, path)
    pruned = "\n".join(line for line in doc.splitlines() if token not in line)
    assert token in doc
    assert token in missing_items(pruned)


def test_checker_catches_deleted_error_code(doc: str) -> None:
    pruned = doc.replace("`job_not_found`", "")
    assert "code:job_not_found" in missing_items(pruned)


def test_checker_catches_deleted_sse_event(doc: str) -> None:
    pruned = doc.replace("`event: queue`", "").replace("| `queue` |", "")
    assert "event:queue" in missing_items(pruned)


def js_blocks(doc: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in doc.splitlines():
        if current is None and line.strip() == "```js":
            current = []
        elif current is not None and line.strip() == "```":
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def test_sse_js_example_at_most_15_lines(doc: str) -> None:
    blocks = js_blocks(doc)
    sse = [b for b in blocks if any("TextDecoderStream" in line for line in b)]
    assert len(sse) == 1
    assert len(sse[0]) <= 15, len(sse[0])
    assert all(len(b) <= 15 for b in blocks), [len(b) for b in blocks]
