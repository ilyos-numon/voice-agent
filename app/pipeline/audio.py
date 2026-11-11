import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

TARGET_SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MIN_AUDIO_SAMPLES = 1600
SILENCE_RMS = 1e-3


class AudioDecodeError(ValueError):
    """Known container but decoding failed (truncated stream, no audio stream)."""


class NoSpeechError(ValueError):
    """Decoded fine but contains no speech (too short, digital silence, empty transcript)."""


def sniff_format(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[4:8] == b"ftyp":
        return "mp4"
    return None


def decode_audio(data: bytes, sample_rate: int = TARGET_SAMPLE_RATE) -> "np.ndarray":
    import av
    import numpy as np

    chunks: list[np.ndarray] = []
    try:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        with av.open(io.BytesIO(data), mode="r", metadata_errors="ignore") as container:
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
    except Exception as e:
        raise AudioDecodeError("audio decode failed") from e
    if not chunks:
        raise AudioDecodeError("no audio stream")
    pcm = np.concatenate(chunks).astype(np.int16)
    if pcm.size == 0:
        raise AudioDecodeError("no audio stream")
    return (pcm.astype(np.float32) / 32768.0).astype(np.float32)


def rms(pcm: "np.ndarray") -> float:
    import numpy as np

    if pcm.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
