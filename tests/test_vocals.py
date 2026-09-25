import numpy as np

from lts.audio import FPS, HOP, SR
from lts.vocals import apply_vocal_mask, runs, vocal_activity, vocal_mask


def tone(seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_runs():
    x = np.array([1, 1, 0, 0, 1, 0], bool)
    assert runs(x, True) == [(0, 2), (4, 5)]
    assert runs(x, False) == [(2, 4), (5, 6)]


def test_vocal_activity_detects_silence_and_singing():
    backing = tone(6, 0.3)
    assert vocal_activity(np.zeros_like(backing), backing) == 0.0
    assert vocal_activity(tone(6, 0.3), backing) > 0.9


def test_vocal_mask_bridges_breaths_but_not_breaks():
    vocals = np.concatenate([tone(2, 0.3), np.zeros(int(0.3 * SR), np.float32),  # breath
                             tone(2, 0.3), np.zeros(4 * SR, np.float32), tone(2, 0.3)])  # fmt: skip
    mask = vocal_mask(vocals, None, len(vocals) // HOP)
    assert mask[int(2.15 * FPS)]  # the 0.3 s breath is bridged
    assert not mask[int(6.3 * FPS)]  # the 4 s break is not


def test_apply_vocal_mask_leaves_only_blank_where_silent():
    em = np.log(np.full((10, 3), 1 / 3))
    mask = np.array([True] * 5 + [False] * 5)
    out = apply_vocal_mask(em, mask, blank=0)
    assert np.allclose(out[:5], em[:5])
    assert np.all(out[5:, 0] == 0) and np.all(out[5:, 1:] < em[5:, 1:])
