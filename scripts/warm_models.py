"""Download STT and TTS model weights into the local cache (Docker build step).

Usage (from repo root):
  uv run --extra stt --extra tts python scripts/warm_models.py
  uv run python scripts/warm_models.py --dry-run   # print model names only
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TTS_REPO = "supertone-oss-archive/supertonic-3"


def model_names(stt_model: str, tts_voice: str) -> list[str]:
    return [
        f"stt: Systran/faster-whisper-{stt_model} (faster-whisper, int8)",
        f"tts: {TTS_REPO} (supertonic, voice {tts_voice})",
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="print model names without downloading")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from app.config import Settings

    settings = Settings()
    for name in model_names(settings.stt_model, settings.tts_voice):
        print(name)
    if args.dry_run:
        return 0

    from app.pipeline.stt_whisper import WhisperSTT
    from app.pipeline.tts_supertonic import SupertonicTTS

    WhisperSTT(model=settings.stt_model, beam_size=settings.stt_beam_size, warm_up=False)
    print("stt: ready")
    SupertonicTTS(voice=settings.tts_voice, warm_up=False)
    print("tts: ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
