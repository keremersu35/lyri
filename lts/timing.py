"""Final clean-up of word timings, applied to the flat word list in lyric order."""

import numpy as np

from lts.audio import FPS


def enforce_order(words: list[dict]) -> int:
    """Drop timings of words that start before their predecessor (fill_gaps re-times them).

    An out-of-order word would make players skip a whole line. Returns how many were dropped.
    """
    dropped, last = 0, -1.0
    for w in words:
        if w.get("start") is None:
            continue
        if w["start"] < last:
            w["start"] = w["end"] = None
            dropped += 1
        else:
            last = w["start"]
    return dropped


def fill_gaps(words: list[dict]) -> None:
    """Interpolate timings for words the aligner couldn't place (symbols, dropped words)."""
    n = len(words)
    i = 0
    while i < n:
        if words[i].get("start") is not None:
            i += 1
            continue
        j = i
        while j < n and words[j].get("start") is None:
            j += 1
        prev_end = words[i - 1]["end"] if i else (words[j]["start"] if j < n else 0.0)
        next_start = words[j]["start"] if j < n else prev_end + 0.3 * (j - i)
        step = max(next_start - prev_end, 0.0) / (j - i)
        for k in range(i, j):
            t = prev_end + step * (k - i)
            words[k].update(start=t, onset=t, end=t + step, conf=0.0)
        i = j


def extend_ends(words: list[dict], rms: np.ndarray, threshold: float, max_hold: float = 4.0) -> None:
    """CTC marks a sung vowel only once; stretch each word's end across the held note."""
    for i, w in enumerate(words):
        limit = w["end"] + max_hold
        if i + 1 < len(words):
            limit = min(limit, words[i + 1]["start"])
        f = int(w["end"] * FPS)
        while f < len(rms) and (f + 1) / FPS <= limit and rms[f] > threshold:
            f += 1
        w["end"] = max(w["end"], f / FPS)


def clamp_ends(words: list[dict]) -> None:
    """No word may end after the next one starts (and every word lasts at least 20 ms)."""
    for w, nxt in zip(words, words[1:], strict=False):
        w["end"] = max(w["start"] + 0.02, min(w["end"], nxt["start"]))
