# Decisions

Architecture decision records for voice-agent. One entry per decision, newest at the bottom. Do not rewrite old entries. Add a new one that supersedes them.

## ADR-001: 스택 확정

Date: 2026-10-22
Status: Accepted

### Context

아직 코드가 없는 상태에서 스모크 E2E가 돌아가는 최소 스캐폴드를 만들어야 했다. 후속 태스크에서 STT(faster-whisper)·TTS(CosyVoice 또는 XTTS-v2)·로컬 LLM을 붙일 수 있어야 하고, 이번 태스크는 실제 모델 없이 스텁만 쓴다.

환경 확인 결과 (2026-10-22, macOS Darwin 27 / arm64): `python3` = 3.9.6(시스템, 사용 안 함), uv 관리 인터프리터에 3.11.15·3.12.13·3.13.12·3.14.3 존재, `node` v24.12.0, `uv` 0.13.0, `docker` 29.7.2. Playwright 브라우저 캐시(chromium) 존재. 포트 8000·8765 비어 있음. Ollama 미설치.

### Options

| 항목 | 결정 | 근거 |
|---|---|---|
| 언어·런타임 | Python 3.11 (`requires-python = ">=3.11,<3.13"`, `.python-version` = `3.11`) | STT 후보 faster-whisper(ctranslate2)와 TTS 후보 CosyVoice(3.10 권장)·XTTS-v2(coqui-tts 포크, 3.10~3.12) 지원 범위의 교집합. 3.11.15가 이미 설치되어 있어 다운로드 없음. 시스템 3.9는 후보 전부 미지원 |
| 패키지 관리 | uv (`pyproject.toml` + `uv.lock`) | 설치됨(0.13.0). 잠금 파일로 재현성, 인터프리터 선택이 `.python-version` 한 줄. 후속 태스크의 torch 계열 설치도 uv extra로 분리 가능 |
| 웹 프레임워크 | FastAPI + uvicorn | 스트리밍 응답·WebSocket을 나중에 같은 앱에 붙일 수 있다. pydantic 스키마가 그대로 API 계약이 된다 |
| 설정 | pydantic-settings (`app/config.py`, `.env` 로드) | 환경변수 이름을 한 곳에 고정. `cp .env.example .env` 흐름과 일치 |
| 테스트 러너 | pytest (단위: `tests/unit`, E2E: `tests/e2e`) | FastAPI 프로젝트의 기본값 |
| E2E 도구 | httpx(API) + playwright python sync API(페이지 스크린샷). pytest-playwright 플러그인은 쓰지 않음 | 페이지 1개라 플러그인 없이 conftest 픽스처로 충분. 플러그인의 `--base-url` 옵션과 충돌 여지 제거 |
| 린트·타입체크 | ruff(check만) + mypy(`ignore_missing_imports = true`, strict 아님) | 설정을 pyproject에 통합해 별도 설정 파일을 늘리지 않는다 |
| STT (후속) | faster-whisper, 모델 `small` 또는 `medium` CPU int8 | 이번 태스크는 `PassthroughSTT` 스텁 |
| TTS (후속) | 1순위 CosyVoice 2 (한국어 지원), 2순위 XTTS-v2 | 후보 두 개 모두 Python 3.11 가능. 이번 태스크는 `SilentTTS` 스텁(무음 WAV) |
| LLM (후속) | Ollama 로컬 (예: qwen2.5 7B) | 외부 자격증명 없이 재현 가능. 이번 태스크는 `TemplateLLM` 스텁(검색 1위 답변 그대로) |
| 검색 (후속) | rank-bm25 → 이후 임베딩 하이브리드 | 공개 FAQ 수천 건 규모엔 BM25로 충분. 이번 태스크는 `KeywordRetriever` 스텁(토큰 겹침 수) |
| docker | 포함 — 로컬 `uv run`과 docker compose 둘 다 | `docker compose up -d` 시나리오를 지금부터 재현 가능하게. 스텁 앱이라 이미지가 작다 |

### Decision

위 표의 "결정" 열 전부. Python 3.11 + uv + FastAPI/uvicorn + pydantic-settings + pytest(httpx·playwright) + ruff/mypy, 모델 계층은 `app/pipeline/types.py`의 Protocol 뒤에 스텁으로 둔다.

### Why

1. 후속 STT·TTS 후보가 함께 돌 수 있는 Python 버전이 3.10~3.12이고, 3.11은 이미 설치되어 있다.
2. FastAPI는 이후 스트리밍·WebSocket을 같은 앱에 붙일 수 있고 pydantic 스키마가 API 계약 역할을 한다.
3. 파이프라인을 Protocol로 나눠 두면 스텁을 실제 모델로 하나씩 바꿀 수 있다.

이 결정이 틀리게 되는 경우: 선택한 TTS가 3.11을 지원하지 않게 되거나, 지연시간 요구 때문에 Python 밖 런타임이 필요해질 때.
