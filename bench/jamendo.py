"""Word-onset accuracy on the English JamendoLyrics songs (hand-annotated word timings).

    uv run python bench/jamendo.py                 # all 20 English songs
    uv run python bench/jamendo.py --songs 3       # quick check on the first 3

Downloads the dataset from Hugging Face into bench/data/ (CC-licensed audio, for evaluation only)
and prints metrics only. Metrics are computed against each word's annotated onset:
AAE = mean absolute error, PCO@x = share of words within x seconds.
`lag` is when the vocal energy actually rises relative to our word starts (≈0 is ideal).
"""

import argparse
import csv
import difflib
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np
from huggingface_hub import hf_hub_download

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lts.audio import load_audio  # noqa: E402
from lts.pipeline import run, slugify  # noqa: E402

REPO = "jamendolyrics/jamendolyrics"
DATA = Path(__file__).resolve().parent / "data"


def fetch(path: str) -> Path:
    """Download a dataset file; resolve the repo's text 'symlinks' (e.g. '../subsets/en/mp3/x.mp3')."""
    local = Path(hf_hub_download(REPO, path, repo_type="dataset", local_dir=DATA / "jamendo"))
    if local.stat().st_size < 200 and local.read_text(errors="ignore").startswith(".."):
        target = (local.parent / local.read_text().strip()).resolve().relative_to((DATA / "jamendo").resolve())
        real = Path(hf_hub_download(REPO, str(target), repo_type="dataset", local_dir=DATA / "jamendo"))
        local.unlink()
        shutil.copy(real, local)
    return local


def english_songs() -> list[str]:
    meta = fetch("metadata.jsonl")
    songs = [json.loads(line) for line in meta.read_text().splitlines()]
    return [Path(m["file_name"]).stem for m in songs if m["language"] == "en"]


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def onset_errors(truth_words, truth_times, pred) -> np.ndarray:
    sm = difflib.SequenceMatcher(None, [norm(w) for w in truth_words], [norm(w["text"]) for w in pred], autojunk=False)
    return np.array(
        [pred[b + k]["start"] - truth_times[a + k] for a, b, n in sm.get_matching_blocks() for k in range(n)]
    )


def energy_lag_ms(vocals: Path, starts: list[float]) -> int:
    """Where the average vocal energy around word starts rises fastest, in ms after the start."""
    a = load_audio(vocals)
    hop, win = 160, 30  # 10 ms frames, ±300 ms
    n = len(a) // hop
    env = 20 * np.log10(np.sqrt(np.mean(a[: n * hop].reshape(n, hop) ** 2, 1)) + 1e-6)
    segs = [env[c - win : c + win + 1] for c in (int(s * 100) for s in starts) if win <= c < n - win]
    mean = np.mean([s - s[:10].mean() for s in segs], 0)
    return (int(np.argmax(np.convolve(np.diff(mean), np.ones(3) / 3, "same"))) + 1 - win) * 10


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=20, help="evaluate the first N English songs")
    ap.add_argument("--out", type=Path, default=DATA / "out")
    args = ap.parse_args()

    rows = []
    for name in english_songs()[: args.songs]:
        mp3, lyrics = fetch(f"mp3/{name}.mp3"), fetch(f"lyrics/{name}.txt")
        rows_csv = list(csv.reader(fetch(f"annotations/words/{name}.csv").open()))[1:]
        t0 = time.time()
        work = run(mp3, args.out, lyrics_file=lyrics, log=lambda _: None)
        doc = json.loads((work / "lyrics.json").read_text())
        pred = [w for line in doc["lines"] for w in line["words"]]
        truth_times = [float(r[0]) for r in rows_csv]
        e = np.abs(onset_errors(lyrics.read_text().split()[: len(truth_times)], truth_times, pred))
        r = {
            "aae": e.mean(), "pco3": (e < 0.3).mean(), "pco1": (e < 0.1).mean(), "gt1": int((e > 1).sum()),
            "lag": energy_lag_ms(work / "vocals.wav", [w["start"] for w in pred]), "secs": time.time() - t0,
        }  # fmt: skip
        rows.append(r)
        print(
            f"{slugify(name)[:32]:32s} AAE {r['aae']:.3f}s  PCO@.3 {r['pco3']:.0%}  PCO@.1 {r['pco1']:.0%}  "
            f">1s {r['gt1']:3d}  lag {r['lag']:+4d}ms  ({r['secs']:.0f}s)",
            flush=True,
        )
    mean = {k: np.mean([r[k] for r in rows]) for k in ("aae", "pco3", "pco1", "lag")}
    print(
        f"MEAN over {len(rows)} songs: AAE {mean['aae']:.3f}s  PCO@.3 {mean['pco3']:.1%}  PCO@.1 {mean['pco1']:.1%}  "
        f">1s total {sum(r['gt1'] for r in rows)}  lag {mean['lag']:+.0f}ms"
    )


if __name__ == "__main__":
    main()
