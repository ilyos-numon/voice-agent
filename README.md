# voice-agent

Voice assistant for a self-service civic kiosk. Speech in, RAG-grounded answer, speech out, with latency measured per stage.

Status: real STT (faster-whisper small) + real TTS (Supertonic 3) + BM25 retrieval over a public civil-service FAQ (575 entries) + LLM summary by Qwen `qwen3.7-flash` (API, optional; `LLM_BACKEND=qwen`, default is a template stub). Rebuilt on public data.

개인정보: `LLM_BACKEND=qwen` 일 때 질문 문장과 공개 FAQ 답변만 외부 API로 나가며 음성은 외부로 보내지 않는다(STT·TTS 는 기기 안에서 돈다).

## Latency (before / after)

![before/after waterfall](bench/results/waterfall.svg)

Qwen 요약 구성 (현재, `LLM_BACKEND=qwen`, before·after 모두 Qwen):

| 지표 | before (/api/ask) | after (/api/ask-stream) | 비고 |
|---|---|---|---|
| 첫 음성까지 (p50 / p95) | 4135.6 / 6399.3 ms | 2121.2 / 3100.2 ms | 서버 측. before 는 응답 완료 = total_ms |
| 전체 응답 (p50 / p95) | 4135.6 / 6399.3 ms | 4241.5 / 5984.0 ms | total_ms (after 는 마지막 문장 WAV 까지) |
| STT (p50) | 0.0 ms | 0.0 ms | 글자 입력, STT 미포함 |
| 검색 (p50) | 0.0 ms | 0.0 ms | BM25 |
| LLM (p50) | 1266.0 ms | 1248.2 ms | Qwen qwen3.7-flash (API) |
| TTS (p50) | 2938.8 ms | 3291.1 ms | after 는 문장별 합 |
| TTS RTF (동시 1) | 0.19 | 0.20 | tts_ms / 음성 길이 |
| 동시 4 요청 | 미측정 | 미측정 | 이번 범위 밖 |
| 검색 적중 (top1 = 질문 id) | 150/150 | 150/150 | |
| 요청 수 (오류) | 150 (0) | 150 (0) | 50 질문 × 3 회 |

클라이언트 측 첫 음성 p50: before 4140.8 ms / after 2124.1 ms

실행 구성: 글자 입력(STT 미사용), 검색 BM25(`RETRIEVER_BACKEND=bm25`, 공개 FAQ 575건), LLM Qwen `qwen3.7-flash`(`LLM_BACKEND=qwen`, 키는 `.env` 의 `LLM_API_KEY`, 근거 FAQ 1건을 1~3문장으로 요약, 스트리밍), TTS Supertonic 3(`TTS_BACKEND=supertonic`), Apple Silicon CPU, 동시 1요청. after 는 LLM 이 첫 조각을 내는 즉시 그 조각의 TTS 를 시작한다(ADR-007). `/health` 의 `pipeline_mode` 가 `"stub"` 로 기록되지만, 이는 `app/config.py` 의 기본값이자 `build_pipeline` 이 받는 유일한 값(`app/pipeline/runner.py`)일 뿐이고 실제 STT·검색·LLM·TTS 백엔드는 위 `*_BACKEND` 환경변수로 따로 고른다.

LLM 스텁 구성 (이전 측정, 참고): LLM 을 템플릿 스텁(원문 답변 그대로, LLM 0.0 ms)으로 둔 같은 bench 에서 첫 음성 p50 / p95 는 before 4986.1 / 8220.0 ms, after 871.1 / 2214.4 ms 였다. 원본 표는 `git show 11136b7:bench/results/summary.md`. 스텁은 원문 전체를 읽어 TTS 가 길고(after TTS p50 5394.1 ms), Qwen 구성은 답을 1~3문장으로 줄여 TTS 가 짧은 대신(3291.1 ms) 첫 음성 앞에 LLM 첫 조각 대기가 붙는다. 두 구성은 답변 길이가 달라 첫 음성·전체 시간을 직접 비교하지 않는다.

검색·STT 의 `0.0 ms` 는 기록 단위가 0.1 ms(소수 1자리 반올림)라서 나온 값이다. BM25 검색은 300개 레코드 중 대부분이 0.0 또는 0.1 ms(p50 < 0.1 ms), 최댓값 3.4 ms(`bench/results/*.jsonl` 의 `stages.retrieve_ms`).

원본 환경 (참고, 비교 불가): 10.52 s → 7.40 s. 다른 하드웨어·다른 모델·실사용 질문이라 위 표와 비교할 수 없다. 출처 docs/vision.md.

무엇을 바꿨나: 답변 전체를 한 번에 합성하던 `/api/ask` 대신, 문장 단위로 합성해 첫 문장 WAV 부터 보내는 `/api/ask-stream`(SSE, ADR-005). LLM 은 Qwen 스트리밍 출력의 첫 조각(문장 끝, 또는 15자 이상에서 쉼표·연결어미 뒤)부터 TTS 와 겹친다(ADR-007). 측정 설계는 `docs/decisions.md` ADR-006.

```sh
uv sync --extra dev --extra tts --extra stt
LLM_BACKEND=qwen STT_BACKEND=whisper TTS_BACKEND=supertonic RETRIEVER_BACKEND=bm25 FAQ_PATH=data/faq/faq.jsonl uv run --extra tts --extra stt uvicorn app.main:app --host localhost --port 8765 &   # .env 에 LLM_API_KEY
./bench/run.sh --config before     # 질문 50개 × 3회, 약 15분
./bench/run.sh --config after
./bench/summarize.sh               # bench/results/summary.md + waterfall.svg
```

## Run

Default (stub STT/TTS, silent audio, no model download):

```sh
uv sync --extra dev && uv run uvicorn app.main:app --host localhost --port 8765
```

Streaming answer (one SSE `audio` event per sentence, each a complete WAV; events `meta` → `audio`×N → `done`, with `first_audio_ms` in `done.timings`):

```sh
curl -N -X POST localhost:8765/api/ask-stream -H 'Content-Type: application/json' -d '{"text":"주민등록등본 발급"}'
```

Real Korean speech in and out (CPU only, no torch):

```sh
uv sync --extra dev --extra tts --extra stt
STT_BACKEND=whisper TTS_BACKEND=supertonic uv run --extra tts --extra stt uvicorn app.main:app --host localhost --port 8765
```

Open http://localhost:8765. Press 🎤, speak, press 🎤 again to send (recording stops on its own after 15 s; the browser asks for microphone permission once). Typing a question and pressing the button still works. The answer audio tries to autoplay; if the browser blocks it, use the play button.

- STT: `Systran/faster-whisper-small`, CPU int8. First run downloads about 484 MB (model.bin) into `~/.cache/huggingface/hub/` (stored in the shared `blobs/` folder). License: code MIT, weights MIT.
- TTS: `TTS_VOICE` selects the speaker, `F1`~`F5` or `M1`~`M5` (default `F1`). First run downloads about 385~415 MB of ONNX weights into `~/.cache/supertonic3/` (override with `SUPERTONIC_CACHE_DIR`).
- TTS license: model weights OpenRAIL-M (use restrictions apply, commercial use allowed); code MIT. The original developer's GitHub repository was archived in 2026; the weights are mirrored at `supertone-oss-archive/supertonic-3`.

Settings are listed in `.env.example`.

LLM summary with Qwen (optional, needs an API key):

```sh
# .env:  LLM_API_KEY=<your DashScope international key>
LLM_BACKEND=qwen STT_BACKEND=whisper TTS_BACKEND=supertonic RETRIEVER_BACKEND=bm25 FAQ_PATH=data/faq/faq.jsonl uv run --extra tts --extra stt uvicorn app.main:app --host localhost --port 8765
```

- Model `qwen3.7-flash` (`LLM_MODEL`), OpenAI-compatible endpoint `LLM_BASE_URL` (default: DashScope international, Singapore), timeout `LLM_TIMEOUT_S` (default 8 s). Standard library `urllib` only, no new dependency.
- Price (official Model Studio pricing page, updated 2026-10-22): Singapore, 0–32K input tokens, input USD 0.03 / output USD 0.13 per 1M tokens.
- If `LLM_API_KEY` is empty the template stub is used. If the API call fails, times out or returns too little text, the original FAQ answer is spoken instead.
- Privacy: only the question text and the retrieved public FAQ answer are sent to the API; audio never leaves the machine.
- Real-API tests (not in the default commands): `uv run pytest tests/live -q` with the server above running.

FAQ retrieval over public data (BM25, character bigrams, no extra dependency):

```sh
./scripts/prepare_data.sh   # needs `uv sync --extra dev` (openpyxl) first
STT_BACKEND=whisper TTS_BACKEND=supertonic RETRIEVER_BACKEND=bm25 FAQ_PATH=data/faq/faq.jsonl uv run --extra tts --extra stt uvicorn app.main:app --host localhost --port 8765
# search only, no speech models:
RETRIEVER_BACKEND=bm25 FAQ_PATH=data/faq/faq.jsonl uv run uvicorn app.main:app --host localhost --port 8765
```

- `prepare_data.sh` downloads the raw XLSX into `data/raw/` (git-ignored), writes `data/faq/faq.jsonl` and `tests/fixtures/faq_eval.jsonl`, then runs the evaluation. The committed `faq.jsonl` is already the result, so the server runs without this step.
- `RETRIEVER_BACKEND` defaults to `keyword` (the 5 synthetic FAQs in `data/faq/sample_faq.json`). The answer shows `출처: faq-NNN`.
- Data: 경기도 시흥시 챗봇 FAQ 시나리오 (공공데이터포털 15148282, 2025-09-01), license "이용허락범위 제한 없음". 570 public rows (of 704 distinct topics, after near-duplicate, short-row and chatbot-scenario-row removal) + 5 synthetic = 575. The indexed "question" is the dataset's intent name (a short topic such as "어린이 예방접종"), not a full question sentence. Details in `data/README.md`, decision in `docs/decisions.md` ADR-004.

## Test

```sh
uv run pytest tests/unit -q                               # unit, no model needed
uv run pytest tests/data -q                               # retrieval accuracy on data/faq/faq.jsonl
uv run --extra tts --extra stt pytest tests/model -q      # real models, needs the downloads above
```

E2E tests run against a server on `localhost:8765`:

```sh
# server started with the full bm25 command above (whisper + supertonic + bm25): full suite
uv run pytest tests/e2e -q
# server in default stub mode (no model): skip the real-model checks
uv run pytest tests/e2e -q --ignore=tests/e2e/test_tts_real.py --ignore=tests/e2e/test_stt_real.py --ignore=tests/e2e/test_faq_bm25.py
```

The test question audio `tests/fixtures/ask_faq001_ko.wav` is synthesized speech (not a human recording). Regenerate it with:

```sh
uv run --extra tts --extra stt python scripts/make_fixture_audio.py --out tests/fixtures/ask_faq001_ko.wav
```

## Measured latency

On this machine (Apple Silicon, CPU):

- STT (Whisper small int8): model load about 10 s; a 3.7 s spoken question is recognized in about 2.7 s `stt_ms`. Reproduce by starting the server with `STT_BACKEND=whisper` and reading `timings.stt_ms` of `POST /api/ask-audio` (body: the fixture WAV), or the "듣기" value on the demo page.
- TTS (Supertonic 3): model load about 9.9 s, one Korean sentence `tts_ms` about 1.5 s. Reproduce with `TTS_BACKEND=supertonic` and `timings.tts_ms` of `POST /api/ask`, or the "말하기" value on the demo page.
- Sentence-streaming TTS (Supertonic 3, `/api/ask-stream`): the first sentence's audio is ready long before the whole answer is synthesized. `first_audio_ms` = time from request start until the first sentence WAV is ready; full `tts_ms` = sum of per-sentence synthesis.

| answer id | chars | sentences | full tts_ms (A) | first_audio_ms (B) | B / A |
|-----------|-------|-----------|-----------------|--------------------|-------|
| faq-020 | 577 | 8 | 14342.5 | 895.8 | 0.062 |

Reproduce (in-process, real model): `uv run --extra tts --extra stt pytest tests/model/test_tts_stream.py -q -s` (prints `full_tts_ms=… first_audio_ms=… ratio=… sentences=…`). Over HTTP (server in the full bm25 real-model mode above, then `uv run pytest tests/e2e/test_stream_real.py -q`): `/api/ask` `tts_ms` 13688.5, first `audio` event received at 892.0 ms, ratio 0.065.

For the 50-question before/after table see "Latency (before / after)" above.

## Measured retrieval

On this machine (Apple Silicon, CPU), 575 FAQ entries, 42 evaluation queries:

| top1 | top3 | retrieve p50 | retrieve p95 | index build |
|---|---|---|---|---|
| 1.000 | 1.000 | 0.011 ms | 0.029 ms | 1.2~1.5 ms |

Reproduce (prints the same line plus 3 sentinel checks and `RESULT PASS`):

```sh
uv run python scripts/eval_retrieval.py --faq data/faq/faq.jsonl --eval tests/fixtures/faq_eval.jsonl
```

What this number means: the evaluation set (`scripts/make_faq_eval.py`) rewrites indexed intent names with fixed rules (dropped endings, swapped word order, keywords only, spaces removed) plus 2 synthetic sentinels. top1 1.000 shows robustness to spelling, spacing and ending variations of known topics only. It is not the accuracy on real users' free-form speech. An evaluation with human-written questions is follow-up work.
