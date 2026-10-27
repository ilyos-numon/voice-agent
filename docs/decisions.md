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

이 수치의 한계: 평가 세트는 색인된 인텐트명을 규칙(어미 제거·어절 교체·핵심어만·공백 제거)으로 변형한 질의다. top1 1.000은 표기·띄어쓰기·어미 변형에 대한 견고성을 보여줄 뿐, 실제 사용자 자유 발화 정확도가 아니다. 구어체 질문 평가는 ADR-008. 또 질문 필드가 질문 문장이 아니라 주제명이라, 주제명에 없는 표현으로 묻는 질문은 빗나갈 수 있다.

이 결정이 틀리게 되는 경우: 구어체 질문 평가(ADR-008)에서 근사 질문 정확도가 요구 수준에 못 미칠 때(그때 형태소 분석기(kiwipiepy) 또는 임베딩 검색 재검토, 답변 본문 색인 검토), 데이터가 수만 건으로 늘어 서버 시작 시 인덱스 생성이 느려질 때(그때 인덱스 파일 저장), 포털 원본의 라이선스나 다운로드 방식이 바뀔 때.

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

## ADR-006: bench: 글자 입력 50문항 × 3회, before=/api/ask·after=/api/ask-stream

Status: Accepted

### Context

ADR-005 의 실측은 긴 답변 1건(faq-020)뿐이라, 문장 단위 스트리밍이 일반 질문에서도 첫 음성까지의 대기를 줄이는지 보여주지 못했다. 같은 질문 집합을 두 엔드포인트에 똑같이 보내 단계별 시간을 모으고, 표와 폭포 그림으로 남길 재현 가능한 bench 가 필요하다.

### Decision

- 질문 선택(`bench/make_questions.py`): 답변 길이가 하한~상한 안인 FAQ 만 후보로 두고, 평가셋 질의를 파일 순서대로(id 당 1개) 먼저 넣은 뒤 나머지를 답변 길이 분위로 균등 추출해 50개를 채운다. (answer_chars, id) 로 정렬하며 난수는 쓰지 않는다.
- 입력은 글자(텍스트)만, 동시 1요청, 50문항 × 3회. before = `POST /api/ask`, after = `POST /api/ask-stream`.
- 측정 정의: `first_audio_ms` 는 서버 측 요청 시작부터 첫 음성 WAV 준비까지(before 는 응답 완료 = `total_ms`), `total_ms` 는 after 의 경우 마지막 문장 WAV 까지. 클라이언트 측 값(`client_first_audio_ms`)도 함께 기록한다. 검색 적중은 top1 id = 질문 id.
- 레코드 `stages` 는 열린 키 집합(`stt_ms`·`retrieve_ms`·`llm_ms`·`tts_ms` …)으로 서버 `timings` 를 그대로 옮긴다. LLM 이 스텁에서 API 로 바뀌거나 단계가 추가돼도 bench 코드를 고치지 않고 같은 표·그림을 다시 만들 수 있다.

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| 음성 입력 bench | STT 시간이 TTS 개선 효과와 섞이고, 50개 질문의 녹음 fixture 를 새로 만들어야 한다. STT 는 README "Measured latency" 에 따로 있다 |
| 동시 4요청 | CPU 한 대에서 모델 경합이 결과를 지배해 before/after 차이를 흐린다. 이번 범위 밖(표에 "미측정") |
| matplotlib 그림 | 의존성 추가 없이 SVG 를 표준 라이브러리로 직접 쓰는 편이 재현이 가볍다 |

### 실측

이 머신(Apple Silicon, CPU), `bench/results/summary.md`:

| 지표 | before (/api/ask) | after (/api/ask-stream) | 비고 |
|---|---|---|---|
| 첫 음성까지 (p50 / p95) | 4986.1 / 8220.0 ms | 871.1 / 2214.4 ms | 서버 측. before 는 응답 완료 = total_ms |
| 전체 응답 (p50 / p95) | 4986.1 / 8220.0 ms | 5402.4 / 11080.3 ms | total_ms (after 는 마지막 문장 WAV 까지) |

재현: README "Latency (before / after)" 의 명령 블록. 원본 환경 수치(docs/vision.md)는 하드웨어·모델·질문이 달라 비교 불가다.

이 결정이 틀리게 되는 경우: LLM 이 실제 API 로 바뀌어 LLM 시간이 TTS 를 넘어설 때(그때 LLM 토큰 스트리밍까지 포함한 bench 로 확장), 실사용에서 동시 요청이 흔할 때(그때 동시성 bench 추가).

## ADR-007: LLM: Qwen `qwen3.7-flash` API 요약 + 첫 조각 조기 분할

Status: Accepted

### Context

지금까지 LLM 단계는 템플릿 스텁이라 FAQ 원문 전체를 그대로 읽었다. 원문이 길면 TTS 가 길고, 질문에 맞춰 줄이지도 못한다. 근거(검색된 FAQ 1건) 안에서 1~3문장으로 줄이는 실제 LLM 이 필요하다. 단, 키오스크는 오프라인·키 없음에서도 지금처럼 동작해야 하고, 외부로 나가는 데이터는 최소여야 한다.

### Decision

- 공급자·엔드포인트: Alibaba Cloud Model Studio(DashScope) 국제 리전(Singapore)의 OpenAI 호환 `POST {LLM_BASE_URL}/chat/completions`, `stream: true`. 표준 라이브러리 `urllib.request` 로 SSE 를 직접 파싱한다(새 의존성 없음). 모델 `qwen3.7-flash`(`LLM_MODEL`), `temperature` 0.2, `max_tokens` 160, thinking 끔.
- 선택: `LLM_BACKEND=qwen` + `.env` 의 `LLM_API_KEY`. 기본값은 `stub`. 키가 비어 있으면 스텁으로 돈다.
- 근거 프롬프트: 근거에 없는 내용 금지, 1~3문장 존댓말, 숫자·기관명은 원문 그대로, 마크다운 금지. 입력은 질문 문장과 top1 FAQ 답변뿐이다.
- 폴백: 네트워크·HTTP·타임아웃(`LLM_TIMEOUT_S`, 기본 8 s)·파싱 오류이거나 출력이 너무 짧으면 FAQ 원문을 문장 분할해 그대로 읽는다. 이미 조각을 내보낸 뒤 끊기면 받은 데까지만 읽는다.
- 가격 근거: 공식 Model Studio 가격 페이지(2026-10-22 갱신), Singapore 0–32K 입력 구간 입력 USD 0.03 / 출력 USD 0.13 per 1M 토큰. 호출당 입력 약 600·출력 약 120 토큰 추정이면 bench 300회도 USD 0.02 미만이다(추정, 청구액 실측 아님).
- 개인정보: 질문 문장과 공개 FAQ 답변만 외부 API로 나가며 음성은 외부로 보내지 않는다. STT·TTS 는 기기 안에서 돈다.
- 겹침 설계: LLM 이 문장을 낼 때마다(`stream_sentences`) `/api/ask-stream` 이 그 문장의 TTS 를 시작한다. 첫 조각만은 문장 끝을 기다리지 않고, 15자 이상이 쌓인 뒤 쉼표나 연결어미(-고/-며/-면/-서/-데/-만) 뒤 공백에서 먼저 잘라 TTS 로 보낸다(조기 분할). `meta` 의 답변 텍스트는 모델 출력 그대로이고, 오디오 조각 경계만 바뀐다. SSE 이벤트 형식·순서는 그대로다.

### 구조적 한계 (왜 조기 분할인가)

- 스트리밍 LLM 시간의 대부분은 첫 토큰 대기다. 토큰이 나오기 시작하면 짧은 답은 금방 끝나서, 첫 문장이 끝나는 시점이 LLM 종료 직전이 된다. 그러면 "첫 문장 TTS 를 LLM 생성과 겹치는" 창이 작아, 문장 단위 겹침만으로는 첫 음성이 거의 "LLM 전체 + 첫 문장 TTS" 가 된다.
- 문장 단위 겹침만 쓴 코드(커밋 d68b578)로 같은 bench 를 돌렸을 때 첫 음성 p50 은 2755 ms 로 허용치 2200 ms 를 넘었다(결과 파일은 이후 측정으로 덮어씀. 재현은 그 커밋에서 README "Latency" 명령 블록).
- 조기 분할 후(현재 코드) `bench/results/summary.md`: 첫 음성 p50 / p95 2121.2 / 3100.2 ms, LLM p50 1248.2 ms, 오류 0/150.
- 남은 한계: 첫 토큰 대기 자체는 줄지 않는다. 첫 음성은 여전히 LLM 스텁 구성(after p50 871.1 ms, `git show 11136b7:bench/results/summary.md`)보다 늦다. 조기 분할로 첫 조각이 문장 중간에서 끊겨 억양이 어색할 수 있고, 오디오 조각 수가 답변 문장 수보다 1개 많을 수 있다(`tests/live` 는 답변 문장 수 1~3, 오디오 조각 ≤ 4 로 확인).

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| `qwen-flash` (더 빠른 flash 후보) | 플랜 기본값으로 `qwen3.7-flash` 를 측정했다. `LLM_MODEL` 만 바꾸면 되므로 첫 토큰 대기가 문제면 다음 후보(미측정) |
| 로컬 LLM(기기 안) | 개인정보는 더 좋지만 CPU 한 대에서 STT·TTS 와 경합하고 모델 다운로드가 크다. MVP 범위 밖 |
| 다른 API 공급자·SDK(openai 패키지) | 의존성 추가가 필요하고 다중 공급자는 이번 범위 밖. OpenAI 호환 엔드포인트라 `LLM_BASE_URL` 로 교체 여지는 남김 |
| 문장 단위 겹침만(조기 분할 없음) | 위 구조적 한계로 허용치 초과 |
| 원문의 첫 문장을 LLM 과 무관하게 먼저 읽기 | 요약 답변과 내용이 어긋날 수 있어 미채택 |

이 결정이 틀리게 되는 경우: 첫 토큰 대기가 크게 줄거나(그때 조기 분할 제거 검토), 공급자 가격·리전 조건이 바뀔 때, 질문 문장도 외부로 보내면 안 되는 배치 환경일 때(그때 로컬 LLM 또는 스텁).

## ADR-008: 구어체 질문 평가: AI 보조 작성 + 블라인드 brief + 누출 지표 공개

Status: Accepted · Date: 2026-10-23

### Context

ADR-004의 평가 세트(`tests/fixtures/faq_eval.jsonl`, 42건)는 색인된 인텐트명을 규칙으로 변형한 질의라 top1 1.000이 나와도 실제 자유 발화 정확도를 말해 주지 못한다. 인텐트명을 모르는 사람이 상황으로 돌려 묻는 질문에서 BM25(문자 bigram)가 얼마나 맞히는지 따로 재야 한다. 사람 발화 수집은 이번 범위 밖이다.

### Options

| 선택지 | 판단 |
|--------|------|
| 사람 모집해 질문 작성·라벨 | 가장 현실적이지만 모집·동의·개인정보 처리가 필요해 MVP 범위 밖 |
| LLM(AI 보조) 작성 + 통제 절차 | 채택. 인텐트명을 숨긴 brief만 보고 쓰게 하고, 별도 리뷰어가 라벨 감사, 누출 지표를 공개 |
| 규칙 변형 추가 | 기존 세트와 같은 한계(인텐트명 글자 그대로)라 미채택 |

### Decision

- 작성: AI 보조(opus 구현 에이전트)가 `scripts/make_blind_brief.py`(시드 20261023) brief — `target_id`·분류·답변 발췌 400자, 인텐트명 없음 — 만 보고 답 있는 질문 38건 + FAQ 범위 밖 none 8건을 썼다. 지침·검수 기준은 `docs/eval-colloquial.md`.
- 감사: 작성 에이전트와 분리된 AI 리뷰어가 46행 라벨을 감사했다. 지적 FIX 6 + 다듬기 2, 1회 수정 후 재감사 FIX 0. 이후 측정 전에 커밋 `cd36a9e`로 동결했고, 측정 후에는 질문을 고치지 않는다.
- 측정: `scripts/eval_colloquial.py`, BM25 기본 파라미터 `search(query, top_k=3)`. none 행은 검색 결과가 빈 목록일 때만 정답. 정확도 임계값 없음(측정 성공만 검사, `tests/data/test_colloquial_eval.py`).
- 누출 지표: `leak = |B(인텐트명) ∩ B(질문)| / |B(인텐트명)|` (문자 bigram). `leak < 0.34`는 low-leak.

### Why

- 사람 없이 할 수 있는 범위에서 "인텐트명을 베끼지 않은 질문"을 가장 싸게 얻는다. 블라인드 brief와 측정 전 동결이 결과에 맞춘 질문 수정을 막는다.
- leak를 같은 명령으로 두 세트에 공개해, 수치 차이가 질문의 단서량 차이에서 온다는 것을 독자가 직접 확인할 수 있다.

### 실측

재현: `uv run python scripts/eval_colloquial.py --faq data/faq/faq.jsonl --eval tests/fixtures/faq_eval_colloquial.jsonl` (첫 줄)

| 세트 | n_answerable | top1 | top3 | none_correct | overall_top1 | leak_mean | top1 low-leak | top1 high-leak |
|------|--------------|------|------|--------------|--------------|-----------|---------------|----------------|
| 구어체 46 | 38 | 0.289 | 0.421 | 0.375 (n_none=8) | 0.304 | 0.210 | 0.219 (n=32) | 0.667 (n=6) |
| 규칙 기반 42 | 42 | 1.000 | 1.000 | 0.000 (n_none=0) | 1.000 | 0.815 | 0.000 (n=0) | 1.000 (n=42) |

규칙 기반 행은 같은 스크립트에 `--eval tests/fixtures/faq_eval.jsonl`.

### 한계

- 질문은 사람이 아니라 LLM이 썼다. 실제 시민 발화(어휘·길이·오류 분포)와 다를 수 있고, 라벨 감사도 AI 리뷰어가 했다.
- c23은 정답이 faq-323으로 라벨됐지만 faq-322의 답변이 완전히 같아 정답이 사실상 둘이다. 검색은 faq-322를 돌려 오답으로 집계됐다(집계 규칙은 바꾸지 않음).
- `min_score=0`이라 FAQ 범위 밖 질문에도 무언가를 돌려주는 경우가 많아 none_correct가 낮다.
- 38건이라 비율 1건이 약 0.026이다. 구간별(n=6 등) 수치는 흔들림이 크다.

이 결정이 틀리게 되는 경우: 실제 사용자 발화(키오스크 로그·모집 참가자)를 동의 받아 모을 수 있게 될 때(그때 그 세트로 교체), 검색을 개선할 때(답변 본문 색인·형태소 분석·임베딩·점수 하한 — 이 세트로 전후 비교), FAQ가 재생성돼 id가 바뀔 때(그때 brief부터 다시).

## ADR-009: 에이전트 빌더: 메모리 상담원 저장·TTL, 문장 근거 bigram 0.5, 모름 기준 coverage 0.20, 규칙 질문 성적표

Status: Accepted · Date: 2026-10-23

### Context

2차 방향은 "투명한 음성 에이전트 빌더"다. 한 서버가 프리셋 4종과 사용자 상담원 여럿을 동시에 돌리고, 매 턴 근거와 단계별 시간을 보여 주고, 모르는 질문에는 지어내지 않고, 문서만으로 성적표를 만들어야 한다. 계정·DB·새 의존성 없이 CPU 한 대에서 1차의 STT·TTS·BM25(ADR-002~004)를 그대로 재사용하는 것이 전제다. 1차의 `/api/ask*` 경로와 bench 수치(ADR-006·007)는 건드리지 않는다.

### Decision

- **멀티 상담원 저장**: 새 패키지 `app/agents/`. `AgentStore`가 상담원·세션을 프로세스 메모리에만 두고, 만든 시각 + `AGENT_TTL_HOURS`(기본 24) 가 지나면 조회·생성 때 지운다(주입 가능한 `clock` 으로 테스트). 사용자 상담원 상한 `MAX_AGENTS` 200, 넘으면 503 `capacity_full`. 프리셋 4종은 서버 시작 때 `data/presets/` 에서 만들고 읽기 전용(403)·TTL 없음. STT·TTS·LLM 인스턴스는 1차 `Pipeline` 것을 공유하고, 목소리는 같은 TTS 모델의 음성 스타일만 바꾼다. 검색 인덱스(`BM25Index` 재사용)는 상담원별로 캐시하고 만료 때 함께 버린다.
- **문장 근거**: 답 문장 s 와 후보 조각 c 의 `overlap = |B(s) ∩ B(c.text + c.title)| / |B(s)|` (문자 bigram, 1차 `tokenize`). 최대 overlap ≥ 0.5(`GROUNDING_MIN_OVERLAP`)면 `supported`, 인용은 c 안에서 s 와 가장 많이 겹치는 문장. 말투 접두어(`네, `)는 빼고 잰다. 못 넘은 문장은 오류가 아니라 "근거 확인 필요" 표시다.
- **모름 기준**: `coverage = |B(q) ∩ B(top1.title + top1.text)| / |B(q)|`, 두 쪽 모두에서 `GENERIC_BIGRAMS`(요청·어미 표현 14개 — 방법·알려·알려주세요·주세요·어떻게·하나요·해요·돼요·되나요·되요·있나요·인가요·할까요·싶어요 — 의 bigram)를 뺀다. coverage < `MIN_QUERY_COVERAGE` = **0.20** 이면 `unknown` 으로 답하고 `when_unknown` 설정(모른다고 말하기 / 담당자 안내)을 따른다.
- **값 고르는 규칙**(측정 전에 design D3 로 고정): civil-kiosk 프리셋 + ADR-008 구어체 세트로 {0.10, 0.15, 0.20, 0.25, 0.30} 을 재고, 센티널 2개(`주민등록등본 떼려면 뭐 필요해요?`, `등본 떼려면 뭐 필요해요?`)가 grounded 로 남고 BM25 top1 이 맞은 답 있는 행의 90 % 이상이 grounded 로 남는 값 중 가장 큰 값을 고른다. 없으면 0.10.
- **성적표 질문**: LLM 없이 규칙으로 만든다. 1차 `scripts/make_faq_eval.py` 의 변형 규칙 + 반말 어미 규칙, 시드는 조각 id 정렬의 sha256 에서 나와 같은 문서면 같은 질문이 나온다. 조각 1개당 원문 그대로 1 + 사람 말투 1. 음성 채널은 실제 STT·TTS 가 있을 때만, 상담원 기본 목소리와 다른 `calm_male` 로 합성해 16 kHz·앞뒤 400 ms 무음(`bench/make_audio.py` 방식)으로 묻는다. 적중 = top1 이 그 질문을 만든 조각이고 답 종류 grounded. 보고서에는 늘 `caveat` 문구가 붙는다.

### 측정: 모름 기준 값별 결과

재현: `uv run --no-sync python scripts/tune_unknown.py --preset civil-kiosk --eval tests/fixtures/faq_eval_colloquial.jsonl` (`GENERIC_BIGRAMS` 제외 후, 로그 `.ai/tasks/T-20261023-agent-builder/logs/s4-tune-unknown.log`, 재실행 `s4-tune-rerun.log` 도 같은 값)

| MIN_QUERY_COVERAGE | 센티널 2개 grounded | 답 있는 행 유지 (BM25 top1 정답 11행 중) | none 행 잡음 (8행 중) | 규칙 통과 |
|---|---|---|---|---|
| 0.10 | 예 | 11/11 | 5/8 | 예 |
| 0.15 | 예 | 11/11 | 7/8 | 예 |
| 0.20 | 예 | 11/11 | 7/8 | 예 (선택) |
| 0.25 | 예 | 9/11 | 8/8 | 아니오 (82 %) |
| 0.30 | 예 | 8/11 | 8/8 | 아니오 (73 %) |

11행은 ADR-008 구어체 세트 답 있는 38행 중 BM25 top1 이 맞은 행 수(top1 0.289)다.

**`GENERIC_BIGRAMS` 개정 이유**: 처음 규칙(제외 없음)으로는 더 낮은 값(0.15)이 골라졌고, 그 값에서도 식당 프리셋에 민원 질문 `주민등록등본 발급 방법 알려줘` 를 물으면 `방법`·`알려` 같은 요청 표현만으로 식당 FAQ 한 행과 coverage 0.222 가 나와 `unknown` 이 되지 않았다(S4 작업 기록, 이 수치는 개정 전 코드라 지금 명령으로는 재현되지 않는다). 내용어가 아닌 요청·어미 표현은 어느 문서에나 겹치므로 양쪽에서 빼고 같은 규칙으로 다시 쟀다. 개정 후 그 질문의 coverage 는 0 이고, 값은 0.20 으로 올라갔다. 목록에는 내용어(필요·발급·주차 등)를 넣지 않는다.

### 측정: 프리셋 성적표

`scripts/scorecard.py --preset <p> --n 30` (명령 전문과 표는 README "에이전트 빌더 > 성적표"). stub 4종: civil-kiosk 30/30, restaurant 30/30, hospital 30/30, office-policy 29/30, 2회차 비교 4종 모두 REPRO OK. full(whisper·Supertonic, LLM 스텁): civil-kiosk 글자 30/30 음성 28/30 첫 음성 p50/p95 3866.3/7047.0 ms(2회차 3823.7/7694.5, REPRO OK), restaurant 글자 30/30 음성 28/30, 3959.9/4321.9 ms. 음성 오답 4건은 모두 `misheard`(글자로는 맞음).

### 한계

- 규칙 질문은 문서의 제목 표현을 그대로 많이 담는다. ADR-008 에서 같은 종류 규칙 세트는 top1 1.000, 구어체 세트는 0.289 였으므로 성적표 점수는 실사용 정확도를 크게 넘겨 잡는다. 음성 질문도 합성 음성이라 사람 발화보다 깨끗하다.
- bigram 근거는 뜻이 같은 바꿔 쓰기를 `unsupported` 로, 글자를 베꼈지만 틀린 문장을 `supported` 로 볼 수 있다. 요약을 켜면 앞의 경우가 늘 수 있다.
- 모름 기준은 civil-kiosk 와 구어체 46행 한 세트로만 골랐다. 0.20 에서도 none 행 1개는 잡지 못한다. 짧은 합성 FAQ(24행) 프리셋에서 따로 재지 않았다.
- 메모리 저장이라 재시작하면 사용자 상담원·세션·성적표와 공유 링크가 사라진다. 프로세스 1개 기준이라 여러 워커로 띄우면 상담원이 워커마다 따로 있다.

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| SQLite·파일 저장 | 문서를 디스크에 남기면 "메모리에만, 24시간 뒤 삭제" 개인정보 원칙과 어긋나고 삭제 보장 코드가 는다. 데모 범위에선 재시작 손실을 감수 |
| 1차 `Pipeline` 을 멀티 상담원으로 일반화 | bench 수치를 낸 경로와 그 테스트를 건드린다. 새 패키지가 모델 인스턴스만 공유 |
| NLI·임베딩으로 문장 근거 판정 | 새 의존성·모델 다운로드와 턴마다 추가 지연. bigram 은 1차 `tokenize` 만으로 계산해 모델이 필요 없다 |
| BM25 점수 하한으로 모름 판정 | 점수 크기가 문서 수·길이에 따라 달라 상담원마다 값을 따로 맞춰야 한다. coverage 는 0~1 비율이라 한 값을 공유 |
| LLM 이 성적표 질문 생성 | 키·비용이 필요하고 같은 명령으로 같은 질문이 나오지 않아 재현(REPRO) 비교가 안 된다. 기본 꺼짐으로 OUT |
| 질문마다 사람 녹음 | 모집·동의가 필요해 MVP 범위 밖(ADR-008 과 같은 이유) |

이 결정이 틀리게 되는 경우: 사람이 쓴 질문·녹음으로 성적표를 검증할 수 있게 될 때(그때 규칙 질문 점수와 비교해 caveat 문구를 수치로 바꿈), 요약 사용이 기본이 되어 바꿔 쓴 문장의 `unsupported` 비율이 높을 때(그때 근거 판정 재검토), 모름 기준이 다른 프리셋에서 답 있는 질문을 자주 놓칠 때(그때 프리셋별 값 또는 점수 하한 병행), 재시작 후에도 상담원을 유지해야 할 때(그때 암호화 저장과 TTL 삭제 작업).

## ADR-010: 두 페이지 바닐라 화면 (만들기 `/` → 대화 `/talk?agent=`)

Date: 2026-10-23
Status: Accepted (ADR-009 의 계약 확인용 `builder.*` 화면과 `share_path` 값을 대체한다)
대체됨: ADR-011

### Context

빌더 API 계약(`docs/api.md`)은 끝났지만 브라우저 화면은 1차 키오스크(`/`)와 스크린샷용 확인 화면뿐이었다. 처음 온 사람이 링크 하나로 상담원을 고르거나 만들고, 말로 묻고, 영수증·성적표·A/B 를 보는 엔드유저 화면이 필요했다. 제약: CDN·번들러·새 의존성 없음, 기존 `/static` 마운트, `app/main.py` 는 단독 단계, E2E 는 playwright sync API 로 실서버(stub·full)에 붙는다.

### Decision

1. HTML 두 장을 라우트 두 개로 서빙한다. `/` → `home.html`(만들기), `/talk` → `talk.html`(대화). 쿼리(`agent`)는 브라우저가 읽는다.
2. 공통 도우미는 `common.js` 의 `window.VA`(API 래퍼, 오류 code → 화면 문구, SSE 읽기, 순서 보장 음성 대기열, 시간 표시). 페이지 스크립트는 기존과 같은 IIFE.
3. 대화 페이지는 `talk.js`(대화·영수증·마이크·상단)와 `talk-tabs.js`(성적표·A/B)로 나누고, 경계는 `window.VA.talk` 객체와 `va:talk-ready` 이벤트 하나다.
4. 만들기 응답의 경고는 `sessionStorage`(`va:warnings:<agent_id>`)로 대화 페이지에 넘긴다. 201 응답에만 있고 대화 페이지는 새 문서라서다.
5. 영수증은 기본 펼친 `<details open>`. 접기·펼치기에 JS 상태가 없고 키보드·스크린리더 접근이 기본으로 된다.
6. E2E 마이크는 conftest 의 Chromium 가짜 마이크(합성 음성 WAV)를 그대로 쓴다. 권한 거부만 JS `getUserMedia` 덮어쓰기로 만든다.
7. 1차 키오스크는 `/static/index.html` 로 옮겨 그대로 둔다(그 E2E 는 URL 만 바꿈). `builder.*` 와 그 화면 E2E 는 지우고, 같은 범위를 두 페이지 E2E 가 다시 덮는다.
8. `share_path` 를 `/talk?agent=<id>` 로 바꾼다. 옛 경로가 지운 파일을 가리키므로 꼭 필요한 유일한 API 변경이고, `app/api/agents.py` 상수 하나다.

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| 해시 라우팅 SPA 한 장 | 공유 링크는 실제 경로가 더 분명하고, 두 페이지가 나눠 갖는 상태가 거의 없다(경고 하나는 sessionStorage) |
| 프레임워크(React·Vue 등)·번들러 | 새 의존성과 빌드 단계가 생기고 CDN 없이 쓰려면 번들 산출물을 저장소에 넣어야 한다. 화면 두 장 규모에서 얻는 것이 적다 |
| ES 모듈 | 최신 브라우저에선 되지만 기존 코드가 IIFE 라 패턴이 둘이 된다 |
| E2E 마이크를 JS 로 WAV Blob 주입 | 테스트 코드가 늘고 실제 `MediaRecorder` 경로를 거치지 않는다 |

### 결과

- 화면에서 상담원 설정 고치기·지우기, 지식 조각 목록, 요약 스위치는 없다(API 로만). 대기열 표시("앞에 N명")는 실제 동시 요청이 필요해 E2E 없이 코드 리뷰로만 확인한다.
- stub 서버 E2E 회귀에서 빼는 파일이 `test_two_page_voice_real.py` 를 더해 8개가 됐다(README Test 절).
- 이 결정이 틀리게 되는 경우: 화면이 세 장 이상으로 늘거나 페이지 사이 상태가 많아질 때(그때 SPA·모듈 재검토), 공개 배포에서 공유 링크가 재시작 뒤에도 살아야 할 때(ADR-009 저장 결정과 함께 재검토).

## ADR-011: Stitch 최종 화면으로 교체 (탐색 `/studio` → 워크스페이스 `/studio/app?agent=`)

Date: 2026-10-23
Status: Accepted (ADR-010 의 두 페이지 화면을 대체한다. `share_path` 는 그대로 둔다)

### Context

ADR-010 의 두 페이지 화면은 계약을 확인하는 데는 충분했지만, 상담원 고르기·만들기·대화·자료·설정·성적표·A/B 를 한 흐름으로 보여 주는 화면이 아니었다. Stitch 로 화면 시안 7장을 만들었고(`design/stitch/README.md`), 이 중 무엇을 쓸지, 시안의 스크립트와 수치를 어떻게 다룰지 정해야 했다. 제약은 ADR-010 과 같다: CDN·번들러·새 의존성 없음, 같은 출처, 백엔드 API·`docs/api.md` 는 바꾸지 않음.

### Decision

1. **최종 화면 3장**: #1 `1_fab34a`(탐색, `/studio`), #3 `3_eb37d0`(워크스페이스, `/studio/app`), #5 `5_da2b7a`(#3 의 네트워크 실패 패널). 근거는 HTML 을 직접 확인한 결과다: #1 은 탐색 시안 중 유일하게 스크립트가 `/api/presets`·`/api/options`·`/api/agents` 를 부르고, #3 은 #2 의 상위 집합(근거 배지·자료 목록·성적표·A/B 패널이 각 API 에 연결)이며 404 복구 카드를 갖는다.
2. **마크업만 가져오고 스크립트는 새로 쓴다**: 시안의 마크업·Tailwind 클래스는 `app/static/studio/{studio.html,workspace.html}` 로 옮기고 인라인 스크립트는 버린다. 스크립트는 `api.js`(공통), `studio.js`, `ws-core.js`, `ws-chat.js`, `ws-knowledge.js`, `ws-settings.js`, `ws-scorecard.js`, `ws-compare.js` 로 나누고 `window.StudioAPI`·`window.WS` 로만 주고받는다.
3. **같은 출처 벤더링**: Tailwind Play 런타임 3.4.16(forms·container-queries 플러그인)과 Material Symbols Outlined 서브셋(고정 아이콘 목록)을 `app/static/studio/vendor/` 에 두고 출처·버전·라이선스·SHA-256·재생성 명령을 `vendor/README.md` 에 적는다. 글꼴은 시스템 한국어 글꼴로 대체한다.
4. **라우트**: `/studio`·`/studio/app` 은 `app/static/studio/` 파일을 돌려주고, `/` 는 `/studio` 로, `/talk` 는 쿼리를 그대로 붙여 `/studio/app` 으로 307 리다이렉트한다. `share_path`(`/talk?agent=<id>`)는 바꾸지 않는다. 옛 링크는 리다이렉트로 살고, 워크스페이스는 `agent_id` 로 자기 공유 주소를 만든다(`docs/api.md` §5.3 이 허용).
5. **내 상담원 목록**: 서버 목록 API 를 추가하지 않는다. 만들 때 `localStorage` 에 id 를 적고, 열 때 `GET /api/agents/{id}` 로 확인해 404 면 지운다.
6. **근거 없는 수치·요소 제거**: 백엔드에 출처가 없는 것은 화면에서 뺀다. 가동률·평균 지연·카드별 평균 응답·프리셋 버전·등급 글자, 사용자 아바타·이름, 목소리 미리듣기, 시스템 프롬프트·말하기 속도·온도, "영구 보관으로 저장"·"설정 복제하기"·만료 시뮬레이션·상태 시뮬레이션 버튼, 목(Mock) 토글. 서버 상태는 `GET /health`, 능력은 `GET /api/options` 의 값만 보여 준다. 기능 소개 문구도 `docs/api.md` 에 있는 동작(음성은 서버 밖으로 나가지 않음, 답마다 근거와 시간, 자동 성적표)으로 바꾼다.
7. **보관**: 쓰지 않는 Stitch 시안 #0·#2·#4·#6 은 `design/stitch/archive/`, 두 페이지 화면은 `app/static/archive/two-page/`, 1차 키오스크는 `app/static/archive/kiosk/`(계속 제공, `/static/archive/kiosk/index.html` 에서 E2E), 두 페이지 E2E 는 `tests/archive/e2e/`(pytest 수집 제외). 파일 내용은 바꾸지 않고 옮기기만 하며, 옛 경로·대체 화면 표는 각 폴더의 `README.md` 에 둔다.

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| 시안 #6(가동률 표시판) 또는 #2(정적 성적표) | API 호출이 없고 백엔드에 없는 수치를 보여 준다 |
| 시안 인라인 스크립트를 그대로 사용 | 목 모드·하드코딩 선택지가 섞여 있고 한 파일이 커서 단계별로 나눠 고치기 어렵다 |
| Tailwind CLI 로 정적 CSS 빌드 | 빌드 도구가 생기고 스크립트 단계마다 다시 빌드해야 한다. Play 런타임은 스크립트가 붙이는 클래스도 처리한다 |
| CDN 의 Tailwind·Google Fonts 직접 로드 | 같은 출처 원칙과 오프라인 데모가 깨진다 |
| `share_path` 를 `/studio/app?agent=` 로 변경 | API·`docs/api.md` 드리프트가 생기고, 리다이렉트로 같은 결과를 얻는다 |
| 서버에 상담원 목록 API 추가 | 계정이 없어 "내 것" 을 서버가 구분할 수 없고, 백엔드를 건드리지 않는 범위를 넘는다 |

### 결과

- Play 런타임이 브라우저에서 CSS 를 만들기 때문에 첫 렌더 전에 스크립트를 내려받아 실행하고, 콘솔에 운영용이 아니라는 경고가 뜬다. 포트폴리오 데모로는 받아들인다.
- 서브셋에 없는 아이콘은 글자로 보인다. 아이콘을 늘릴 때는 `vendor/README.md` 의 목록과 재생성 명령을 따른다.
- README 스크린샷(`docs/images/two-page-*.png`)은 옛 화면 그대로다(재촬영은 별도 태스크).
- 이 결정이 틀리게 되는 경우: 화면 수나 상호작용이 늘어 Play 런타임의 첫 렌더 비용이 문제될 때(그때 CLI 빌드 재검토), 공유 링크를 서버 밖 프론트엔드에서 열어야 할 때(그때 `share_path` 와 CORS 재검토), 여러 브라우저에서 같은 "내 상담원" 목록이 필요할 때(그때 계정·목록 API 재검토).

## ADR-012: 상담원 검색 조사 떼기·CSV 답변 색인·질문 맞춤 문장

Date: 2026-10-27
Status: Accepted (ADR-009 의 검색·답 구성 규칙을 고친다. 근거 0.5 규칙·모름 기준 0.20 은 그대로)

### Context

가상의 헬스장 샘플(`data/samples/fitness-center.txt` 14조각, `fitness-center.csv` 18행)로 상담원을 만들어 기본 설정(friendly·short·say_unknown·요약 꺼짐)으로 물었더니 세 가지가 틀렸다. 요약 꺼짐은 LLM 없이 규칙으로 답을 조립하므로(`turn.py:iter_turn`) 원인은 모두 코드에 있다.

1. CSV "일요일에도 문 열어요?" → "자료에 없다". CSV 는 질문 칸만 색인해 답변에만 있는 "일요일"을 못 찾았다. 어절 전체 글자 bigram 이라 "일요일**에도**"의 `에도` 가 "당일**에도**"(휴관 문장)와도 겹쳤다.
2. "PT 당일 취소하면 어떻게 돼요?" → 가격 문장만. 답 문장을 질문과 무관하게 조각 앞에서 N개 잘랐고, 취소 규정은 3번째 문장이었다.
3. CSV "수영장 있어요?" → "네, 요가는…". `있어요` 가 요청·어미 표현 목록에 없어 `있어` 가 내용어로 남아 "그룹 수업은 언제 있어요?" 행이 모름 기준을 넘었고, friendly 말투는 무조건 `네, ` 를 붙였다.

제약: 새 의존성 없음, 레거시 키오스크 검색기(`app/pipeline/bm25.py`)·근거 계산(`grounding.py`)·모름 기준값(0.20)·프리셋 성적표는 바꾸지 않음.

### Decision

1. **D1 조사 떼기 토크나이저** (`retrieval.py:agent_tokenize`): NFC·소문자 → 낱말 `[0-9a-z가-힣]+` → 낱말 끝 조사 27개(에서도·에서는·에게는·으로는·에서·에게·으로·까지·부터·에도·에는·이랑·하고·처럼·보다·은·는·이·을·를·에·도·의·와·과·로·만) 중 긴 것부터 맞는 첫 하나를, 떼고 나서 2글자 이상 남을 때만 한 번 뗀다 → 남은 낱말이 1글자면 그대로, 아니면 글자 bigram. 상담원 검색(`ChunkIndex`)과 모름 판정(`query_coverage`) 모두 이것을 쓴다. 주격 `가` 는 넣었다가 restaurant 성적표 한 문항("채식 메뉴가 …")이 떨어져 뺐다.
2. **D2 CSV 질문+답변 색인** (`knowledge.py:parse_faq_csv`): `index_text = 질문 + "\n" + 답변`. 제목=질문, 본문=답변은 그대로. civil-kiosk(`faq_jsonl`) 색인은 바꾸지 않는다.
3. **D3 `있어요` 를 요청·어미 표현에 추가**: `_GENERIC_PHRASES` 15개. `GENERIC_BIGRAMS` 도 `agent_tokenize` 로 만든다.
4. **D4 질문 맞춤 문장 고르기** (`compose.py:select_sentences`): 1위 조각의 재생 단위 문장마다 `|질문 내용어 토큰 ∩ 문장 토큰|` 점수를 매겨 높은 문장부터 N개(동점은 문서 순서). 모두 0이면 앞에서 N개. 요약 꺼짐 경로와 LLM 이 문장을 하나도 안 낸 경우의 원문 대체에 쓴다.
5. **D5 `네, ` 조건화** (`compose.py:shape_sentences(..., query)`): friendly 말투라도 첫 문장이 질문과 내용어 토큰을 1개 이상 나눌 때만 `네, ` 를 붙인다. 요약 켜짐의 LLM 문장(첫 문장 선제 TTS 포함)에도 같은 조건을 적용한다. 의문사 질문("어디", "얼마")에서 빼는 규칙은 넣지 않았다.

### 대안과 미채택 이유

| 대안 | 미채택 이유 |
|------|-------------|
| `app/pipeline/bm25.py:tokenize` 자체를 고친다 | 1차 키오스크 검색과 `tests/data` 기준 수치(ADR-004·008)가 이 함수에 걸려 있다. 상담원 검색만 별도 토크나이저로 바꾸면 기존 측정을 다시 할 필요가 없다 |
| 형태소 분석기(예: kiwipiepy) 도입 | 새 의존성·모델 파일·첫 로드 시간이 생긴다. 이번 결함 세 개는 고정 조사 목록으로 고쳐진다 |
| 동의어 사전 | 도메인마다 따로 만들어야 하고 사용자가 올린 자료에 맞출 방법이 없다 |
| `네, ` 를 아예 없애거나 의문사 질문에서만 뺀다 | 기존 단위 테스트(`주차는 어디에 하나요?` → `네, `)와 친절 말투의 의미가 바뀐다. 겹침 조건만으로 "수영장 있어요?"류 오답 접두는 막힌다 |
| 모름 기준(0.20)을 올린다 | civil-kiosk 구어체 세트에서 정한 값(ADR-009)이다. 0.25 이상은 답할 수 있는 질문 11개 중 2개를 버린다(아래 표) |

### 측정

모든 명령은 저장소 루트에서, `STUB="LLM_BACKEND=stub STT_BACKEND=stub TTS_BACKEND=stub"`, `T=.ai/tasks/T-20261027-retrieval-quality`.

| 측정 | 명령 | 변경 전 | 변경 후 |
|------|------|---------|---------|
| 프리셋 성적표 text (n=30, 음성 없음) | `$STUB uv run --no-sync python scripts/scorecard.py --preset <p> --n 30 --no-voice --out $T/after-s3/<p>.json` | civil-kiosk 30/30 · restaurant 30/30 · hospital 30/30 · office-policy 29/30 | 30/30 · 30/30 · 30/30 · 29/30 (비악화) |
| 모름 기준 civil-kiosk | `uv run --no-sync python scripts/tune_unknown.py --preset civil-kiosk --eval tests/fixtures/faq_eval_colloquial.jsonl` | `cov=0.20 kept_answerable=11/11 none_caught=7/8`, `CHOSEN 0.20` | 같음 (0.25 는 `kept_answerable=9/11`) |
| 단위 테스트 | `uv run pytest tests/unit -q` | 403 passed | 429 passed |
| 피트니스 12질문 (규칙 경로, 기본 설정) | 변경 전: `git archive e638e16 app` 을 임시 폴더에 풀어 `PYTHONPATH` 앞에 두고 같은 질문 6개 × 두 자료를 `ChunkIndex.search` → `is_unknown` → 답 문장 → `ground_sentences` 로 실행. 변경 후: 같은 방식을 현재 트리로 실행. 서버를 거친 같은 판정은 E2E `tests/e2e/test_fitness_samples.py` | 텍스트 4/6 · CSV 3/6 | 텍스트 6/6 · CSV 6/6 |

피트니스 판정 기준: 일요일·PT 취소 질문은 기대한 조각이 1위이고 **첫 문장**에 핵심 구절이 있을 것, "수영장 있어요?"는 모름 문장 1개(`네,` 없음), 나머지는 기대 조각 1위 + 답에 핵심 구절, 그리고 첫 문장 근거 있음. 변경 전 텍스트는 일요일 질문(첫 문장이 평일 시간)과 PT 취소 질문이, CSV 는 일요일·PT 취소·수영장 질문이 틀렸다.

### 결과

- 상담원 검색과 레거시 키오스크 검색이 다른 토크나이저를 쓴다. 근거 계산(`grounding.py`)은 여전히 어절 전체 글자 bigram 이다.
- 답 문장 순서가 문서 순서가 아닐 수 있다(질문과 가장 많이 겹치는 문장이 먼저).
- 조사 목록은 고정이다. 목록에 없는 어미·조사 결합이나 뜻이 같은 다른 낱말("쉬는 날" ↔ "휴관")은 여전히 못 잇는다.
- 이 결정이 틀리게 되는 경우: 짧은 낱말(2~3글자)이 조사처럼 끝나 잘못 잘리는 사례가 성적표에서 반복될 때(그때 목록 축소 또는 형태소 분석기 재검토), CSV 답변이 길어 질문 칸 일치가 묻힐 때(그때 질문 칸 가중치 재검토).
