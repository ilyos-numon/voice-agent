# voice-agent

Voice assistant for a self-service civic kiosk. Speech in, RAG-grounded answer, speech out, with latency measured per stage.

Status: Scaffold + real TTS (Supertonic 3). STT, LLM and retrieval are still stubs. Rebuilt on public data.

## Run

Default (stub TTS, silent audio, no model download):

```sh
uv sync --extra dev && uv run uvicorn app.main:app --host localhost --port 8765
```

Real Korean TTS (Supertonic 3, CPU only, no torch):

```sh
uv sync --extra dev --extra tts
TTS_BACKEND=supertonic uv run --extra tts uvicorn app.main:app --host localhost --port 8765
```

Open http://localhost:8765, type a question and press the button. The answer audio tries to autoplay; if the browser blocks it, use the play button.

- Voice: `TTS_VOICE` selects the speaker, `F1`~`F5` or `M1`~`M5` (default `F1`).
- First run downloads about 385~415 MB of ONNX weights into `~/.cache/supertonic3/` (override with `SUPERTONIC_CACHE_DIR`). Later runs load from the cache.
- License: model weights OpenRAIL-M (use restrictions apply, commercial use allowed); code MIT.
- The original developer's GitHub repository was archived in 2026; the weights are mirrored at `supertone-oss-archive/supertonic-3`.

Settings are listed in `.env.example`.

## Test

```sh
uv run pytest tests/unit -q                 # unit, no model needed
uv run --extra tts pytest tests/model -q    # real model, needs the download above
```

E2E tests run against a server on `localhost:8765`:

```sh
# server started with TTS_BACKEND=supertonic: full suite
uv run pytest tests/e2e -q
# server in default stub mode (no model): skip the real-TTS checks
uv run pytest tests/e2e -q --ignore=tests/e2e/test_tts_real.py
```

## Measured latency

Supertonic 3 on this machine (Apple Silicon, CPU): model load about 9.9 s, one Korean sentence `tts_ms` about 1.5 s. Reproduce by starting the server with `TTS_BACKEND=supertonic` and reading the `timings.tts_ms` field of `POST /api/ask`, or the "말하기" value on the demo page.
