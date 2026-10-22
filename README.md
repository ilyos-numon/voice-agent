# voice-agent

Voice assistant for a self-service civic kiosk. Speech in, RAG-grounded answer, speech out, with latency measured per stage.

Status: real STT (faster-whisper small) + real TTS (Supertonic 3). Retrieval and LLM are still stubs. Rebuilt on public data.

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

## Test

```sh
uv run pytest tests/unit -q                               # unit, no model needed
uv run --extra tts --extra stt pytest tests/model -q      # real models, needs the downloads above
```

E2E tests run against a server on `localhost:8765`:

```sh
# server started with STT_BACKEND=whisper TTS_BACKEND=supertonic: full suite
uv run pytest tests/e2e -q
# server in default stub mode (no model): skip the real-model checks
uv run pytest tests/e2e -q --ignore=tests/e2e/test_tts_real.py --ignore=tests/e2e/test_stt_real.py
```

The test question audio `tests/fixtures/ask_faq001_ko.wav` is synthesized speech (not a human recording). Regenerate it with:

```sh
uv run --extra tts --extra stt python scripts/make_fixture_audio.py --out tests/fixtures/ask_faq001_ko.wav
```

## Measured latency

On this machine (Apple Silicon, CPU):

- STT (Whisper small int8): model load about 10 s; a 3.7 s spoken question is recognized in about 2.7 s `stt_ms`. Reproduce by starting the server with `STT_BACKEND=whisper` and reading `timings.stt_ms` of `POST /api/ask-audio` (body: the fixture WAV), or the "듣기" value on the demo page.
- TTS (Supertonic 3): model load about 9.9 s, one Korean sentence `tts_ms` about 1.5 s. Reproduce with `TTS_BACKEND=supertonic` and `timings.tts_ms` of `POST /api/ask`, or the "말하기" value on the demo page.
