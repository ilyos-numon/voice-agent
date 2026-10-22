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

## ADR-002: TTS 엔진: Supertonic 3 (CPU 우선)

Date: 2026-10-22
Status: Accepted (ADR-001의 "TTS 1순위 CosyVoice 2, 2순위 XTTS-v2"를 대체한다)

### Context

개발·데모 머신은 GPU가 없는 arm64 macOS(CPU-only, RAM 16 GB)다. 이전 TTS 후보 순위는 GPU를 전제로 했다. 키오스크 응답 목표는 "한국어 1문장 합성 3초 이내"이고, 설치는 torch 없이 `uv sync --extra tts` 한 번으로 끝나야 한다.

### Options

| 후보 | torch | 모델 크기 | 한국어 | CPU 1문장 | 라이선스 | 판정 |
|---|---|---|---|---|---|---|
| Supertonic 3 (`supertonic` 1.3.1, ONNX) | 불필요 | ≈ 415 MB | 공식 지원(`ko`) | 실측 ≈ 1.6 s | 가중치 OpenRAIL-M, 코드 MIT | 채택 |
| MeloTTS | 필요 | 208 MB | 지원 | RTF < 1 추정 | MIT | 제외 (3.11 arm64 설치 불가·고정 핀 다수) |
| CosyVoice 2 | 필요 | ≈ 4.9 GB | 지원 | 수십 초 추정 | Apache-2.0 | 제외 (CPU 비현실적, 공식 pip 없음) |
| XTTS-v2 | 필요 | ≈ 2.1 GB | 지원 | 5~15 s 추정 | 코드 MPL-2.0, 가중치 CPML(비상업) | 제외 (공개 포트폴리오 부적합) |
| Piper (`ko_KR/kss`) | 불필요 | 수십 MB | 1 음색 | 매우 빠름 | 코드 GPL-3.0, 음성 CC BY-NC-SA 추정 | 예비 |

### Decision

`TTS_BACKEND=supertonic`이면 `app/pipeline/tts_supertonic.py`의 `SupertonicTTS`(음색 `TTS_VOICE`, 기본 `F1`, `lang="ko"`, `total_steps=8`)를 쓴다. 기본값은 `TTS_BACKEND=stub`(`SilentTTS`)이고, stub 경로는 `supertonic`을 import하지 않는다.

### Why

1. wheel만으로 설치되고 torch가 필요 없다 (의존성 onnxruntime·numpy·soundfile·huggingface-hub).
2. 한국어를 공식 지원한다.
3. CPU-only 16 GB 머신에서 실측 1문장 합성이 3초 이내다 (S2 실측: 1문장 1.6 s, 모델 로드 9.9 s).
4. 다운로드 크기가 후보 중 작은 편이다.

라이선스:
- 모델 가중치: OpenRAIL-M (사용 제한 조항 있음, 상업 이용 가능).
- 코드: MIT (설치된 패키지 메타데이터 `License-Expression` 값. `License` 필드는 비어 있음).

모델 캐시: `~/.cache/supertonic3/` 최상위에 ONNX 4개, 실측 385 MB (`SUPERTONIC_CACHE_DIR`로 변경 가능). 첫 실행 시 자동 다운로드.

원 개발사 GitHub 저장소는 2026년에 보관(archived) 처리됐고, 가중치는 `supertone-oss-archive/supertonic-3`로 미러돼 있다. 패키지가 고정한 원 모델 저장소 `Supertone/supertonic-3`는 2026-10-22 기준 접근 가능하다.

이 결정이 틀리게 되는 경우: 원 모델 저장소와 미러 모두 접근할 수 없게 될 때, CPU에서 1문장 합성이 3초를 넘게 될 때, GPU를 도입해 CosyVoice 2 같은 대형 모델이 현실적이 될 때(그때 CosyVoice 2 재검토).
