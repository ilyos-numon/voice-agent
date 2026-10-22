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

## ADR-003: STT 엔진: faster-whisper small (CPU int8)

Date: 2026-10-22
Status: Accepted (ADR-001의 "STT (후속): faster-whisper, 모델 `small` 또는 `medium` CPU int8"을 `small` 기본으로 확정한다)

### Context

개발·데모 머신은 GPU가 없는 arm64 macOS(CPU-only, RAM 16 GB)다. 키오스크 응답 목표는 "5초 발화를 3초 이내 인식"이고, 설치는 torch 없이 `uv sync --extra stt` 한 번으로 끝나야 한다. 지금까지 STT는 `PassthroughSTT` 스텁(텍스트 그대로 통과)이었다.

### Options

| 후보 | torch | 모델 크기 | 한국어 | CPU 5초 발화 | 라이선스 | 판정 |
|---|---|---|---|---|---|---|
| faster-whisper 1.2.1 (`Systran/faster-whisper-small`, CTranslate2) | 불필요 | small ≈ 486 MB (base 148 MB, medium 1,531 MB) | 지원, `initial_prompt`로 도메인 철자 유도 | 실측 ≈ 2.6~3.0 s (small int8) | 코드 MIT, 가중치 MIT | 채택 |
| openai-whisper | 필요 | 동일 가중치 | 동일 | small fp32 4~8 s 추정 | MIT | 제외 (torch, 느림) |
| sherpa-onnx (한국어 zipformer) | 불필요 | 수십~수백 MB 추정 | 공개 모델 1종, 품질 자료 없음 | 매우 빠름 | Apache-2.0 | 예비 (스트리밍 후속 후보) |
| Vosk (`vosk-model-small-ko-0.22`) | 불필요 | ≈ 82 MB 추정 | 소형 모델이라 낮음 추정 | 빠름 | Apache-2.0 | 제외 (품질) |
| Apple Speech (SFSpeechRecognizer) | - | OS 내장 | 좋음 | 빠름 | - | 제외 (macOS 전용, Docker·재현 불가) |

### Decision

`STT_BACKEND=whisper`이면 `app/pipeline/stt_whisper.py`의 `WhisperSTT`(모델 `STT_MODEL`, 기본 `small`, `device="cpu"`, `compute_type="int8"`, `language="ko"`)를 쓴다. 빔 크기는 `STT_BEAM_SIZE`, 기본 1(greedy)이다. S3 실측에서 3.73초 픽스처 인식이 beam 5 2.97 s, beam 1 2.64 s였고 두 경우 텍스트가 같았다. beam 5는 3초 상한에 0.03 s 여유뿐이라 실행 편차로 넘을 수 있어 beam 1을 기본으로 한다. 도메인 어휘(주민등록등본·가족관계증명서·인감증명서·무인발급기·수수료·신분증)를 `initial_prompt`로 준다. 무음·잡음 환청을 막으려고 모델 호출 전 RMS 게이트(0.1 s 미만 또는 RMS < 1e-3 → 인식 거부)와 `vad_filter=True`를 함께 쓰고, 인식 결과가 빈 문자열이어도 거부한다. 기본값은 `STT_BACKEND=stub`(`PassthroughSTT`)이고, stub 경로는 `faster_whisper`·`av`를 import하지 않는다.

### Why

1. wheel만으로 설치되고 torch가 필요 없다 (ctranslate2·av·tokenizers·huggingface-hub·onnxruntime).
2. Whisper 계열은 한국어 인식이 검증돼 있고 `initial_prompt`로 민원 어휘 철자를 유도할 수 있다.
3. CPU-only 16 GB 머신에서 small int8이 목표 안에 들어온다 (S3 실측: 모델 로드 9.94 s, 3.73초 픽스처 인식 beam 1 2.64 s, S4 파이프라인 `stt_ms` 2708.6, 인식 결과 "주민등록등본 때려면 뭐 필요해요?" → faq-001).
4. medium(1,531 MB)은 품질이 낫지만 CPU에서 3초 목표를 넘을 것으로 추정돼 대안으로 남긴다 (`STT_MODEL=medium`으로 전환 가능).

라이선스:
- 코드: MIT (faster-whisper, CTranslate2).
- 모델 가중치: MIT (Hugging Face 태그 `license:mit`, 원 OpenAI Whisper 가중치 MIT).

모델 캐시: `~/.cache/huggingface/hub/models--Systran--faster-whisper-small/`. 첫 실행 시 자동 다운로드(≈ 486 MB). model.bin ≈ 484 MB(483,546,902 B)는 hf-hub 중복 제거 레이아웃에 따라 공용 blobs 폴더(`~/.cache/huggingface/hub/blobs/`)에 저장되므로 모델 디렉토리만 `du`하면 수 MB로 보인다.

오디오 입력 경로: 브라우저 MediaRecorder(`audio/webm;codecs=opus`) → 요청 raw 본문 → 서버에서 `av`로 디코드·16 kHz mono float32 리샘플(`app/pipeline/audio.py`) → `WhisperSTT`. WAV 픽스처도 같은 경로로 디코드된다.

테스트 픽스처(`tests/fixtures/ask_faq001_ko.wav`)는 사람 녹음이 아니라 TTS로 합성한 음성이다. 실측 인식 품질·지연은 합성 음성 기준이며, 실제 사람 발화(억양·잡음·마이크 품질)에서는 다를 수 있다. 실측 결과의 "때려면"(떼려면)처럼 어휘 일부가 틀려도 검색 키워드가 맞으면 답변은 맞다.

이 결정이 틀리게 되는 경우: 실제 사람 발화에서 small의 한국어 오인식이 잦아 검색이 빗나갈 때(그때 `medium` 또는 다른 엔진 재검토), CPU에서 5초 발화 인식이 3초를 넘게 될 때, 스트리밍(부분 인식) 요구가 생길 때(그때 sherpa-onnx 재검토), GPU를 도입해 large 계열이 현실적이 될 때.

## ADR-004: 검색: 공개 민원 FAQ + 직접 구현 BM25(문자 bigram)

Date: 2026-10-22
Status: Accepted (ADR-001의 "검색 (후속): rank-bm25"를 직접 구현 BM25 + 어절 내 문자 bigram으로 바꾼다)

### Context

지금까지 검색은 합성 FAQ 5건(`data/faq/sample_faq.json`)에 대한 `KeywordRetriever`(키워드 일치 스텁)였다. 데모가 "실제 민원 질문에 답한다"를 보여주려면 수백 건 이상의 실제 FAQ가 필요하고, 그 데이터는 누구나 같은 명령으로 다시 받아 같은 결과를 만들 수 있어야 한다(로그인·인증키 없음, 재배포 가능 라이선스). 토큰화는 STT 오인식("떼려면/때려면")과 조사·어미 변형을 견뎌야 한다.

### Options

데이터 (2026-10-22 공공데이터포털에서 확인):

| 후보 | 형식·규모 | 라이선스 | 판정 |
|---|---|---|---|
| 경기도 시흥시_챗봇 FAQ 시나리오 (15148282) | XLSX 295,757 B, 민원 전 분야 | 이용허락범위 제한 없음 | 채택 |
| 서울특별시 성동구_AI챗봇 학습용 데이터셋 (15166816) | JSON, 1,259건 | 이용허락범위 제한 없음 | 대안 (후속 병합 후보) |
| 국민권익위원회_국민신문고 민원질의응답 원문 (15164540) | CSV 26 MB, 20,058행 | 이용허락범위 제한 없음 | 제외 (답변이 길고 민원인 원문 포함) |
| 서울 다산콜센터 FAQ (15119373) | OpenAPI | 공공누리 1유형 | 제외 (인증키 필요) |
| 고용노동부·법률구조공단 상담 데이터 | XLSX·CSV | 공공누리 3·4유형 (변경금지) | 제외 (전처리와 충돌) |
| Hugging Face 민원 응답 데이터 | JSONL 100 MB | 재배포 조건 불명확 | 제외 |

검색기·토큰화:

| 항목 | 후보 | 판정 |
|---|---|---|
| BM25 구현 | `rank-bm25`(numpy, 역색인 없음) / `bm25s`(numpy·scipy) / 직접 구현(역색인, 표준 라이브러리) | 직접 구현 — 수백~수천 건이면 짧은 코드로 충분하고 기본 의존성이 늘지 않는다. 동점은 낮은 인덱스 우선(결정적) |
| 토큰화 | 어절 내 문자 bigram / kiwipiepy(모델 수십 MB, 로드 수 초 추정) / python-mecab-ko(C 빌드) | 문자 bigram — 의존성 0, 오인식·조사 변형에 강하다 |
| 인덱스 | 파일 저장 / 메모리 생성 | 메모리 생성 — 서버 시작 때 만든다 |

### Decision

`RETRIEVER_BACKEND=bm25`이면 `app/pipeline/bm25.py`의 `BM25Retriever`(k1=1.2, b=0.75)가 `FAQ_PATH`(공개 데이터는 `data/faq/faq.jsonl`)를 읽어 **질문 필드만** 색인한다. 기본값은 `RETRIEVER_BACKEND=keyword`(기존 `KeywordRetriever` + 합성 5건)로, TTS·STT와 같은 "기본 stub, 실제는 환경변수" 관례와 기존 테스트를 유지한다.

데이터는 `./scripts/prepare_data.sh`가 만든다: 원본 XLSX 다운로드 → 정규화(`scripts/prepare_faq.py`) → 평가 세트 생성 → 평가. 원본에 질문 문장 열이 없어 질문 필드는 `인텐트명`(2어절 안팎의 주제명)이다. 전처리: 답변에서 HTML·이메일·URL·전화번호 제거, 담당자·연락처·링크 열 미출력, 챗봇 시나리오 표기 답변(`|` 포함) 행 제외, IPv4 형태 포함 행 제외, 정확·근사(질문 bigram Jaccard ≥ 0.6) 중복 제거, 익명화 검사에 걸린 행은 `data/faq/exclude_keys.txt`에 key로 제외. 합성 5건은 faq-001~005로 맨 앞에 그대로 둔다 — 기존 단위·E2E 테스트와 음성 픽스처가 faq-001을 기준으로 하고, 근사 중복 규칙에서 합성과 겹치는 공개 행이 빠지게 하기 위해서다.

### Why

1. 로그인·인증키 없이 표준 라이브러리로 받을 수 있고 포털에 이용허락범위 "제한 없음"이 명시돼 있어 재현·재배포가 된다.
2. 민원 전 분야 FAQ라 키오스크 데모 도메인과 맞는다.
3. 직접 구현 BM25 + 문자 bigram은 의존성을 늘리지 않고, 이 규모에서 검색 지연이 음성 단계(초 단위)에 비해 무시할 수준이다.

라이선스: 이용허락범위 제한 없음 (공공데이터포털 `15148282`, 제공 경기도 시흥시, 데이터 기준일 2025-09-01, 다운로드 2026-10-22). 출처 표기: `https://www.data.go.kr/data/15148282/fileData.do`.

실측 (이 머신(Apple Silicon, CPU), `./scripts/prepare_data.sh`):
- 원본 12시트, raw_rows 1428 = 전체 시트 714 + 분야별 시트 714(중복). 고유 행 714, 인텐트명 고유 704.
- 탈락 short 2 · scenario 14 · exact_dup 590 · near_dup 252 · pattern 0 · excluded 0. 정리 phones 304 · urls 106 · emails 4.
- 결과 575건(합성 5 + 공개 570), 476,391 B. 인덱스 생성 1.2~1.5 ms.
- 평가 42건(`uv run python scripts/eval_retrieval.py --faq data/faq/faq.jsonl --eval tests/fixtures/faq_eval.jsonl`): top1 1.000, top3 1.000, 검색 p50 0.011 ms, p95 0.029 ms, 센티널 3건 OK.

이 수치의 한계: 평가 세트는 색인된 인텐트명을 규칙(어미 제거·어절 교체·핵심어만·공백 제거)으로 변형한 질의다. top1 1.000은 표기·띄어쓰기·어미 변형에 대한 견고성을 보여줄 뿐, 실제 사용자 자유 발화 정확도가 아니다. 사람이 쓴 질문 세트로 하는 평가는 후속 과제다. 또 질문 필드가 질문 문장이 아니라 주제명이라, 주제명에 없는 표현으로 묻는 질문은 빗나갈 수 있다.

이 결정이 틀리게 되는 경우: 사람이 쓴 질문 평가에서 근사 질문 정확도가 요구 수준에 못 미칠 때(그때 형태소 분석기(kiwipiepy) 또는 임베딩 검색 재검토, 답변 본문 색인 검토), 데이터가 수만 건으로 늘어 서버 시작 시 인덱스 생성이 느려질 때(그때 인덱스 파일 저장), 포털 원본의 라이선스나 다운로드 방식이 바뀔 때.

## ADR-005: 문장 단위 스트리밍 TTS: SSE + 문장별 WAV

Status: Accepted

### Context

긴 FAQ 답변(예: faq-020, 577자)은 전체를 한 번에 합성하면 CPU에서 14 s 넘게 걸려, 키오스크 사용자는 그동안 아무 소리도 듣지 못한다. 답변을 문장으로 나눠 첫 문장이 합성되는 즉시 재생을 시작하면 체감 대기를 1문장 합성 시간으로 줄일 수 있다. 기존 `/api/ask`·`/api/ask-audio` 응답 형식은 바꾸지 않는다.

### Decision

`POST /api/ask-stream`(텍스트)·`POST /api/ask-audio-stream`(음성)을 추가한다. 응답은 SSE(`text/event-stream`, Starlette `StreamingResponse`, 새 의존성 없음)이고 이벤트 순서는 `meta` 1개 → `audio` 문장 수만큼(index 0부터) → `done` 1개, 스트림 중 오류는 `error` 1개로 끝낸다. 각 `audio`는 문장 하나의 **완전한 WAV**를 base64로 싣는다(기존 `audio_wav_b64`와 같은 형식이라 클라이언트가 `<audio>`로 바로 재생). 데모 페이지는 문장 순서대로 이어 재생한다.

문장 분할(`app/pipeline/sentences.py`, 표준 라이브러리 `re`만): 줄바꿈과 `.`·`?`·`!`·`。` 뒤 공백/끝을 경계로 한다(숫자 사이 점, 공백 없는 점은 경계 아님). 10자 미만 조각은 다음 조각에 붙이고(마지막이면 앞 조각에), 150자 초과 조각은 150자 이내 마지막 `, ` 또는 공백에서 자른다. 공백을 빼면 원문과 같다(무손실).

`first_audio_ms`: 요청 처리 시작(`iter_ask` 진입)부터 index 0 문장 WAV가 준비된 시각까지(ms, 소수 1자리). `done.timings.tts_ms`는 문장별 `tts_ms` 합.

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| WebSocket | 요청 1개 → 응답 스트림 1개인 단방향 흐름이라 양방향 채널이 필요 없다. 연결 관리·재연결 코드가 늘고 curl로 확인하기 어렵다 |
| 바이너리 오디오 청크 스트리밍(PCM 조각) | 브라우저에서 MediaSource/WebAudio 버퍼 관리가 필요하고, Supertonic이 문장 단위로 합성하므로 문장보다 잘게 나눠도 첫 음성이 빨라지지 않는다 |
| 전체 합성 + 다음 답변 prefetch | 질문을 미리 알 수 없어 첫 응답 대기는 그대로다 |

### 실측

이 머신(Apple Silicon, CPU), faq-020(577자, 8문장):
- 인프로세스(`uv run --extra tts --extra stt pytest tests/model/test_tts_stream.py -q -s`): full_tts_ms 14342.5, first_audio_ms 895.8, 비율 0.062.
- HTTP 경유(실모델 서버 + `uv run pytest tests/e2e/test_stream_real.py -q`): `/api/ask` tts_ms 13688.5, 첫 `audio` 이벤트 수신 892.0 ms, 비율 0.065.

전체 합성 시간 자체는 줄지 않는다(문장 합 ≈ 전체). 줄어드는 것은 첫 음성까지의 대기다.

이 결정이 틀리게 되는 경우: 첫 문장이 매우 길어 1문장 합성이 수 초를 넘을 때(그때 분할 상한 축소 또는 청크 스트리밍 재검토), 문장 재생 시간이 다음 문장 합성 시간보다 짧아 문장 사이에 끊김이 들릴 때(그때 선합성 버퍼 검토), 대화형 끼어들기(barge-in) 같은 양방향 제어가 필요해질 때(그때 WebSocket 재검토).
