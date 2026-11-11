"""Synthesize a Korean question WAV fixture with Supertonic and resample it.

Usage (from repo root):
  uv run --extra tts --extra stt python scripts/make_fixture_audio.py \
      --out tests/fixtures/ask_faq001_ko.wav
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TEXT = "주민등록등본 떼려면 뭐 필요해요?"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True, type=Path, help="output WAV path")
    p.add_argument("--text", default=DEFAULT_TEXT, help="sentence to synthesize")
    p.add_argument("--rate", type=int, default=16000, help="output sample rate (Hz)")
    p.add_argument("--pad-ms", type=int, default=400, help="silence padding at both ends (ms)")
    p.add_argument("--voice", default="F1", help="Supertonic voice style")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    import numpy as np

    from app.pipeline.audio import decode_audio
    from app.pipeline.tts_supertonic import SupertonicTTS
    from app.pipeline.wav import pcm16_to_wav

    wav_bytes = SupertonicTTS(voice=args.voice, warm_up=False).synthesize(args.text)
    speech = decode_audio(wav_bytes, sample_rate=args.rate)
    pad = np.zeros(args.rate * args.pad_ms // 1000, dtype=np.float32)
    signal = np.concatenate([pad, speech, pad])
    pcm = (np.clip(signal, -1.0, 32767 / 32768) * 32768.0).round().astype("<i2")
    data = pcm16_to_wav(pcm.tobytes(), args.rate, 1)

    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    duration_s = len(pcm) / args.rate
    print(f"wrote {out} bytes={len(data)} duration_s={duration_s:.3f} rate={args.rate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
