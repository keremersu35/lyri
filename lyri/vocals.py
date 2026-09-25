"""What the separated vocal stem tells us: is anyone singing, and where."""

import numpy as np

from lyri.audio import FPS, SR, frame_rms, to_db


def vocal_activity(vocals: np.ndarray, instrumental: np.ndarray) -> float:
    """Fraction of 0.5 s windows that carry real singing (below ~3% the track is instrumental).

    Demucs always leaves some residue in the vocal stem, so a window counts only when the
    vocals are loud in absolute terms and not far below the backing track.
    """
    v, m = to_db(frame_rms(vocals, SR // 2)), to_db(frame_rms(instrumental, SR // 2))
    n = min(len(v), len(m))
    if n == 0:
        return 0.0
    return float(np.mean((v[:n] > -38) & (v[:n] > m[:n] - 18)))


def vocal_mask(vocals: np.ndarray, instrumental: np.ndarray | None, n_frames: int) -> np.ndarray:
    """Per-emission-frame 'someone is singing' mask."""
    v = to_db(frame_rms(vocals))[:n_frames]
    smooth = np.ones(5) / 5  # 100 ms
    v = np.convolve(v, smooth, "same")
    active = v > max(np.percentile(v, 95) - 30, -50)
    if instrumental is not None:
        m = np.convolve(to_db(frame_rms(instrumental)), smooth, "same")[: len(v)]
        active[: len(m)] &= v[: len(m)] > m - 24  # separation bleed under a loud backing track
    active = _close_gaps(active, int(0.5 * FPS))  # breaths between words
    active = _drop_short(active, int(0.15 * FPS))  # isolated clicks
    active = _dilate(active, int(0.25 * FPS))  # don't clip consonant onsets
    mask = np.zeros(n_frames, bool)
    mask[: len(active)] = active
    return mask


def apply_vocal_mask(emission: np.ndarray, mask: np.ndarray, blank: int, penalty: float = 12.0) -> np.ndarray:
    """Make characters very unlikely where nobody sings, so words can't drift into instrumental breaks.

    A soft penalty (not -inf) keeps quiet singing the detector missed reachable.
    """
    em = emission.copy()
    active = np.ones(len(em), bool)  # stems and mix can differ by a frame or two
    active[: min(len(em), len(mask))] = mask[: len(em)]
    em[~active] -= penalty
    em[~active, blank] = 0.0
    return em


def vocal_envelope(vocals: np.ndarray) -> tuple[np.ndarray, float]:
    """Per-frame RMS of the vocal stem and a 'still singing' threshold (for held notes)."""
    rms = frame_rms(vocals)
    audible = rms[rms > 1e-4]
    return rms, 0.12 * np.percentile(audible, 90) if len(audible) else 1.0


def runs(x: np.ndarray, value: bool) -> list[tuple[int, int]]:
    """[start, end) index ranges where `x == value`."""
    edges = np.flatnonzero(np.diff(np.r_[False, x == value, False].astype(np.int8)))
    return list(zip(edges[::2], edges[1::2], strict=True))


def _close_gaps(x: np.ndarray, width: int) -> np.ndarray:
    x = x.copy()
    for a, b in runs(x, False):
        if b - a < width and a > 0 and b < len(x):
            x[a:b] = True
    return x


def _drop_short(x: np.ndarray, width: int) -> np.ndarray:
    x = x.copy()
    for a, b in runs(x, True):
        if b - a < width:
            x[a:b] = False
    return x


def _dilate(x: np.ndarray, width: int) -> np.ndarray:
    return np.convolve(x.astype(np.int32), np.ones(2 * width + 1, np.int32), "same") > 0
