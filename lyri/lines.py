"""Line-level alignment strategies built on the word aligner."""

import numpy as np

from lyri.aligner import Aligner
from lyri.audio import FPS
from lyri.ctc import normalize_word
from lyri.lyrics import Lyrics

Timed = list[dict | None]  # per-word timings of one line


def align_global(aligner: Aligner, emission: np.ndarray, lines: list[list[str]]) -> list[Timed]:
    """Align the whole lyrics text against the whole track in one Viterbi pass."""
    flat = aligner.align(emission, [w for line in lines for w in line])
    out, i = [], 0
    for line in lines:
        out.append(flat[i : i + len(line)])
        i += len(line)
    return out


def align_windowed(
    aligner: Aligner, emission: np.ndarray, lines: list[list[str]], starts, ends, pad: float = 1.0
) -> list[Timed]:
    """Align each line only inside its own time window (lines can't disturb each other)."""
    out = []
    for words, s, e in zip(lines, starts, ends, strict=True):
        f0, f1 = max(0, int((s - pad) * FPS)), min(len(emission), int((e + pad) * FPS))
        out.append(aligner.align(emission[f0:f1], words, f0) if f1 > f0 else [None] * len(words))
    return out


def line_start(timed: Timed) -> float:
    return next((t["start"] for t in timed if t), float("inf"))


def line_conf(timed: Timed) -> float:
    confs = [t["conf"] for t in timed if t]
    return float(np.mean(confs)) if confs else 0.0


def repair_with_synced(aligner, emission, lines, timed, lrc_times, duration, log) -> list[Timed]:
    """Re-align lines whose placement disagrees with synced-LRC line times.

    The LRC may be offset against this recording, so we first estimate that offset from
    confident lines, then re-align outliers inside their LRC window and keep the result
    only when it is more confident.
    """
    starts = [line_start(t) for t in timed]
    diffs = [
        s - r for s, r, t in zip(starts, lrc_times, timed, strict=True) if s != float("inf") and line_conf(t) > 0.3
    ]
    if not diffs:
        return timed
    offset = float(np.median(diffs))
    log(f"align: synced lyrics are {offset:+.2f}s off against this audio")
    fixed = 0
    for i, s in enumerate(starts):
        expected = lrc_times[i] + offset
        if abs(s - expected) <= 1.5 and line_conf(timed[i]) >= 0.5:
            continue
        end = lrc_times[i + 1] + offset if i + 1 < len(lrc_times) else min(duration, expected + len(lines[i]) + 2)
        local = align_windowed(aligner, emission, [lines[i]], [expected], [end], pad=1.5)[0]
        if line_conf(local) > line_conf(timed[i]) + 0.05:
            timed[i], fixed = local, fixed + 1
    if fixed:
        log(f"align: re-aligned {fixed} line(s) using synced timestamps")
    return timed


def transcript_lyrics(transcript: dict, max_words: int = 9, max_gap: float = 1.0) -> Lyrics:
    """Turn Whisper segments into short display lines with approximate start/end times."""
    lines, starts, ends = [], [], []

    def flush(words):
        lines.append(" ".join(w["word"] for w in words))
        starts.append(words[0]["start"])
        ends.append(words[-1]["end"])

    for seg in transcript["segments"]:
        cur: list[dict] = []
        for w in seg["words"]:
            if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > max_gap):
                flush(cur)
                cur = []
            cur.append(w)
        if cur:
            flush(cur)
    return Lyrics(lines, starts, "transcription", extra={"ends": ends})


def drop_unsung(transcript: dict, mask: np.ndarray | None, log) -> dict:
    """Whisper invents text over instrumental breaks; keep only segments where someone sings."""
    if mask is None:
        return transcript
    keep = [seg for seg in transcript["segments"] if _mask_share(mask, seg["start"], seg["end"]) >= 0.3]
    if len(keep) < len(transcript["segments"]):
        log(f"lyrics: dropped {len(transcript['segments']) - len(keep)} transcript segment(s) over instrumentals")
    return {**transcript, "segments": keep}


def add_missing_passages(aligner, emission, texts, display, timed, transcript, mask, log):
    """Insert sung passages the lyrics text lacks (a skipped chorus repeat, a missing verse).

    A confident Whisper segment over active vocals that no lyric line landed on is aligned in
    its own window and merged in chronological order. `texts` are the line strings and
    `display` their words. Returns (texts, display, timed, indices of the inserted lines).
    """
    spans = [(line_start(t), max(x["end"] for x in t if x)) for t in timed if any(t)]
    heard = []
    for seg in transcript["segments"]:
        words = seg["words"]
        if len(words) < 3 or np.mean([w["prob"] for w in words]) < 0.6:
            continue
        if any(a < seg["end"] + 0.5 and seg["start"] - 0.5 < b for a, b in spans):
            continue
        if mask is not None and _mask_share(mask, seg["start"], seg["end"]) < 0.5:
            continue
        heard.append(seg)
    if not heard:
        return texts, display, timed, set()
    log(f"align: {len(heard)} sung passage(s) missing from the lyrics text -> adding what was heard")
    h_display = [seg["text"].split() for seg in heard]
    h_norm = [[normalize_word(w) for w in line] for line in h_display]
    h_timed = align_windowed(aligner, emission, h_norm, [s["start"] for s in heard], [s["end"] for s in heard], pad=0.5)
    all_texts, all_display = texts + [seg["text"] for seg in heard], display + h_display
    all_timed = timed + h_timed
    order = sorted(range(len(all_timed)), key=lambda k: line_start(all_timed[k]))
    inserted = {pos for pos, k in enumerate(order) if k >= len(texts)}
    return [all_texts[k] for k in order], [all_display[k] for k in order], [all_timed[k] for k in order], inserted


def _mask_share(mask: np.ndarray, start: float, end: float) -> float:
    a = int(start * FPS)
    return float(mask[a : max(int(end * FPS), a + 1)].mean())
