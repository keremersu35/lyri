"""Exact-timing check: macOS text-to-speech words placed at known times over a backing track.

    uv run python bench/synthetic.py path/to/instrumental.mp3

Speech is easier than singing, so this is a sanity check of the whole machinery
(separation, alignment, timing clean-up), not a measure of lyric accuracy.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lyri.audio import load_audio  # noqa: E402
from lyri.pipeline import run  # noqa: E402

SR = 44100
TEXT = """i walked along the river where the water rests
the morning light was golden on my chest
and every stone remembers what we said
hold me closer now before the night is gone
we were running through the city with our hearts on fire
never looking back we only wanted higher"""  # original text written for this test


def build(backing: Path, folder: Path) -> tuple[Path, Path, list[dict]]:
    bed = load_audio(backing, SR) * 0.8
    rng, t, truth = np.random.default_rng(0), 3.0, []
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "w.aiff"
        for li, line in enumerate(TEXT.splitlines()):
            for word in line.split():
                rate = str(int(rng.integers(140, 200)))
                subprocess.run(["say", "-v", "Samantha", "-r", rate, "-o", str(clip), word], check=True)
                a = load_audio(clip, SR)
                nz = np.flatnonzero(np.abs(a) > 0.01)
                a = a[nz[0] : nz[-1] + 1]
                s = int(t * SR)
                if s + len(a) >= len(bed):
                    break
                bed[s : s + len(a)] += a * 0.9
                truth.append({"word": word, "start": t, "line": li})
                t += len(a) / SR + float(rng.uniform(0.05, 0.35))
            t += float(rng.uniform(1.5, 4.0))
    song, lyrics = folder / "Synthetic_Test_Song.wav", folder / "lyrics.txt"
    pcm = (bed / max(1.0, np.abs(bed).max() / 0.98) * 32767).astype("<i2")
    with wave.open(str(song), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())
    lyrics.write_text(TEXT + "\n")
    return song, lyrics, truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("backing", type=Path, help="any instrumental track (1.5+ minutes)")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        song, lyrics, truth = build(args.backing, Path(tmp))
        for label, lyr in (("lyrics given", lyrics), ("no lyrics (transcription)", None)):
            work = run(song, Path(tmp) / "out" / label.split()[0], lyrics_file=lyr, log=lambda _: None)
            pred = [w for line in json.loads((work / "lyrics.json").read_text())["lines"] for w in line["words"]]
            errs, j = [], 0
            for t in truth:
                for k in range(j, min(j + 4, len(pred))):
                    if pred[k]["text"].lower().strip(".,!?") == t["word"]:
                        errs.append(abs(pred[k]["onset"] - t["start"]))
                        j = k + 1
                        break
            e = np.array(errs)
            print(
                f"{label:28s} matched {len(e)}/{len(truth)}  median {np.median(e) * 1000:.0f}ms  "
                f"max {e.max() * 1000:.0f}ms  within 100ms {np.mean(e < 0.1):.0%}"
            )


if __name__ == "__main__":
    main()
