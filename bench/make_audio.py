"""Synthesize one question WAV per bench question with Supertonic (<out-dir>/<id>.wav).

Usage (from repo root):
  uv run --extra tts --extra stt python bench/make_audio.py --limit 0 --out-dir bench/audio
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--questions", default="bench/questions.jsonl", type=Path)
    p.add_argument("--out-dir", default="bench/audio", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--rate", type=int, default=16000, help="output sample rate (Hz)")
    p.add_argument("--pad-ms", type=int, default=400, help="silence padding at both ends (ms)")
    p.add_argument("--voice", default="F1", help="Supertonic voice style")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    lines = args.questions.read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    if args.limit > 0:
        questions = questions[: args.limit]

    import numpy as np

    from app.pipeline.audio import decode_audio
    from app.pipeline.tts_supertonic import SupertonicTTS
    from app.pipeline.wav import pcm16_to_wav

    tts = SupertonicTTS(voice=args.voice, warm_up=False)
    pad = np.zeros(args.rate * args.pad_ms // 1000, dtype=np.float32)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for q in questions:
        text = q["query"].replace("_", " ")
        speech = decode_audio(tts.synthesize(text), sample_rate=args.rate)
        signal = np.concatenate([pad, speech, pad])
        pcm = (np.clip(signal, -1.0, 32767 / 32768) * 32768.0).round().astype("<i2")
        (out_dir / f"{q['id']}.wav").write_bytes(pcm16_to_wav(pcm.tobytes(), args.rate, 1))
        print(f"{q['id']} duration_s={len(pcm) / args.rate:.3f}", file=sys.stderr, flush=True)
    print(f"wrote {len(questions)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
