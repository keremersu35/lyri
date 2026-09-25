"""Audio decoding via ffmpeg, and the frame grid shared by the aligner and vocal analysis."""

import json
import subprocess
from pathlib import Path

import numpy as np

SR = 16000  # every model in the pipeline runs at 16 kHz
HOP = 320  # samples per CTC emission frame
FPS = SR / HOP  # 50 emission frames per second


def load_audio(path: Path, sr: int = SR) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` Hz."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, np.float32).copy()


def probe_duration(path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, check=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


def frame_rms(audio: np.ndarray, hop: int = HOP) -> np.ndarray:
    """RMS level of each non-overlapping `hop`-sample frame."""
    n = len(audio) // hop
    return np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1))


def to_db(x: np.ndarray) -> np.ndarray:
    return 20 * np.log10(x + 1e-9)
