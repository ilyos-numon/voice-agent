import subprocess
import sys

import pytest

from app.pipeline.audio import (
    MAX_AUDIO_BYTES,
    MIN_AUDIO_SAMPLES,
    TARGET_SAMPLE_RATE,
    AudioDecodeError,
    NoSpeechError,
    sniff_format,
)
from app.pipeline.stubs import SilentTTS


def test_sniff_wav() -> None:
    assert sniff_format(SilentTTS().synthesize("x")) == "wav"


def test_sniff_webm() -> None:
    assert sniff_format(b"\x1a\x45\xdf\xa3" + b"\x00" * 16) == "webm"


def test_sniff_ogg() -> None:
    assert sniff_format(b"OggS" + b"\x00" * 16) == "ogg"


def test_sniff_mp4() -> None:
    assert sniff_format(b"\x00\x00\x00\x18ftypisom") == "mp4"


@pytest.mark.parametrize("data", [b"", b"hello", b"RIFF1234WAVX"])
def test_sniff_unknown(data: bytes) -> None:
    assert sniff_format(data) is None


def test_errors_are_value_errors() -> None:
    assert issubclass(AudioDecodeError, ValueError)
    assert issubclass(NoSpeechError, ValueError)


def test_constants() -> None:
    assert MAX_AUDIO_BYTES == 10485760
    assert MIN_AUDIO_SAMPLES == 1600
    assert TARGET_SAMPLE_RATE == 16000


def test_import_does_not_load_av() -> None:
    code = "import sys, app.pipeline.audio; print('av' in sys.modules, 'numpy' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False False"
