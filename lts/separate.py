"""Vocal isolation with Demucs."""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Alignment runs on the full mix, so the stems only feed Whisper, the vocal mask and
# note-hold detection; the single htdemucs model is ~2x faster than the htdemucs_ft bag
# and measured no worse for alignment.
DEFAULT_MODEL = "htdemucs"


def _run_with_progress(cmd: list[str], progress, passes: int) -> int:
    """Run demucs, forwarding overall progress (0..1) to `progress`.

    A model bag (e.g. htdemucs_ft = 4 models) runs one tqdm bar per model.
    """
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
    buf, done, last = b"", 0, 0
    while chunk := proc.stderr.read(256):
        buf = (buf + chunk)[-512:]
        pcts = re.findall(rb"(\d{1,3})%\|", buf)
        if pcts:
            pct = int(pcts[-1])
            if pct < last - 50:
                done += 1
            last = pct
            progress(min(1.0, (done + pct / 100) / passes))
    return proc.wait()


def separate_vocals(audio_path: Path, work_dir: Path, model: str = DEFAULT_MODEL, progress=None) -> Path:
    """Write vocals.wav and instrumental.wav into work_dir; cached across runs."""
    vocals = work_dir / "vocals.wav"
    if vocals.exists():
        return vocals

    with tempfile.TemporaryDirectory() as tmp:
        for device in ("mps", "cpu"):
            cmd = [
                sys.executable,
                "-m",
                "demucs",
                "--two-stems",
                "vocals",
                "-n",
                model,
                "-d",
                device,
                "-o",
                tmp,
                "--filename",
                "{stem}.{ext}",
                str(audio_path),
            ]
            code = (
                _run_with_progress(cmd, progress, 4 if model.endswith("_ft") else 1)
                if progress
                else subprocess.run(cmd).returncode
            )
            if code == 0:
                break
            print(f"demucs failed on {device}, retrying", file=sys.stderr)
        else:
            raise RuntimeError("demucs separation failed")

        stem_dir = Path(tmp) / model
        shutil.move(stem_dir / "no_vocals.wav", work_dir / "instrumental.wav")
        shutil.move(stem_dir / "vocals.wav", vocals)
    return vocals
