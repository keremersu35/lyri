"""CTC forced alignment: text normalization and the Viterbi path search (numpy only)."""

import re
import unicodedata

import numpy as np

NEG = -1e30
NUMBERS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten", "&": "and",
}  # fmt: skip


def normalize_word(word: str) -> str:
    """Map a display word to the aligner's alphabet: A-Z and apostrophe ('' if nothing alignable)."""
    w = word.lower().replace("’", "'").replace("‘", "'")
    w = NUMBERS.get(w.strip('.,!?;:"()'), w)
    w = unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z']", "", w).strip("'").upper()


def viterbi(logp: np.ndarray, tokens: np.ndarray, blank: int) -> np.ndarray:
    """Best CTC state path over the blank-interleaved token sequence.

    `logp` is (T, V) frame log-probabilities. Returns (T,) states: even = blank,
    odd state 2j+1 = token j.
    """
    n_frames, n_states = len(logp), 2 * len(tokens) + 1
    ext = np.full(n_states, blank)
    ext[1::2] = tokens
    can_skip = np.zeros(n_states, bool)
    can_skip[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])

    alpha = np.full(n_states, NEG)
    alpha[0] = logp[0, blank]
    alpha[1] = logp[0, ext[1]]
    back = np.zeros((n_frames, n_states), np.int8)
    cols = np.arange(n_states)
    for t in range(1, n_frames):
        step = np.concatenate(([NEG], alpha[:-1]))
        skip = np.where(can_skip, np.concatenate(([NEG, NEG], alpha[:-2])), NEG)
        cand = np.stack([alpha, step, skip])
        best = cand.argmax(0)
        alpha = cand[best, cols] + logp[t, ext]
        back[t] = best

    s = n_states - 1 if alpha[-1] >= alpha[-2] else n_states - 2
    path = np.empty(n_frames, np.int64)
    for t in range(n_frames - 1, -1, -1):
        path[t] = s
        s -= back[t, s]
    return path


def token_frames(path: np.ndarray, n_tokens: int) -> list[list[int]]:
    """Frames assigned to each token by a Viterbi path."""
    frames: list[list[int]] = [[] for _ in range(n_tokens)]
    for t, s in enumerate(path):
        if s % 2:
            frames[s // 2].append(t)
    return frames
