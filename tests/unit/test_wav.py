import math
import struct

import pytest

from app.pipeline.stubs import SilentTTS
from app.pipeline.wav import (
    EXPECTED_SAMPLE_RATE,
    MIN_DURATION_S,
    MIN_RMS,
    pcm16_to_wav,
    wav_stats,
)


def _sine_pcm(freq: float, seconds: float, amplitude: int, sample_rate: int) -> bytes:
    n = int(sample_rate * seconds)
    samples = [round(amplitude * math.sin(2 * math.pi * freq * i / sample_rate)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def test_silent_tts_stats() -> None:
    stats = wav_stats(SilentTTS().synthesize("x"))
    assert stats.sample_rate == 16000
    assert stats.channels == 1
    assert stats.sample_width == 2
    assert stats.frames == 1600
    assert stats.duration_s == pytest.approx(0.1, abs=0.001)
    assert stats.rms == 0.0


def test_sine_wave_rms_and_duration() -> None:
    pcm = _sine_pcm(1000, 1.0, 10000, 44100)
    stats = wav_stats(pcm16_to_wav(pcm, 44100))
    assert stats.rms == pytest.approx(7000, abs=200)
    assert stats.duration_s == pytest.approx(1.0, abs=0.001)


def test_roundtrip_frames() -> None:
    pcm = _sine_pcm(440, 0.25, 5000, 44100)
    assert wav_stats(pcm16_to_wav(pcm, 44100)).frames == len(pcm) // 2


def test_not_wav_raises() -> None:
    with pytest.raises(ValueError, match="not a WAV"):
        wav_stats(b"not wav")


def test_odd_length_pcm_raises() -> None:
    with pytest.raises(ValueError):
        pcm16_to_wav(b"\x00\x00\x00", 44100)


def test_thresholds() -> None:
    assert MIN_DURATION_S == 0.5
    assert MIN_RMS == 200.0
    assert EXPECTED_SAMPLE_RATE == 44100
