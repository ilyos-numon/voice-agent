import io
import math
import struct
import wave
from dataclasses import dataclass

MIN_DURATION_S = 0.5
MIN_RMS = 200.0
EXPECTED_SAMPLE_RATE = 44100


@dataclass(frozen=True)
class WavStats:
    sample_rate: int
    channels: int
    sample_width: int
    frames: int
    duration_s: float
    rms: float


def wav_stats(data: bytes) -> WavStats:
    if data[:4] != b"RIFF":
        raise ValueError("not a WAV")
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            sample_rate = w.getframerate()
            channels = w.getnchannels()
            sample_width = w.getsampwidth()
            frames = w.getnframes()
            raw = w.readframes(frames)
    except (wave.Error, EOFError) as e:
        raise ValueError("not a WAV") from e
    if sample_width != 2:
        raise ValueError("only 16-bit PCM supported")
    n = len(raw) // 2
    samples = struct.unpack(f"<{n}h", raw[: n * 2])
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
    duration_s = frames / sample_rate if sample_rate else 0.0
    return WavStats(sample_rate, channels, sample_width, frames, duration_s, rms)


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    if len(pcm) % (2 * channels) != 0:
        raise ValueError(f"pcm length {len(pcm)} is not a multiple of {2 * channels}")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
