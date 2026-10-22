# voice-agent

Voice assistant for a self-service civic kiosk. Speech in, RAG-grounded answer, speech out, with latency measured per stage.

Status: real STT (faster-whisper small) + real TTS (Supertonic 3) + BM25 retrieval over a public civil-service FAQ (575 entries). The LLM is still a stub. Rebuilt on public data.

## Run

Default (stub STT/TTS, silent audio, no model download):

```sh
uv sync --extra dev && uv run uvicorn app.main:app --host localhost --port 8765
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
