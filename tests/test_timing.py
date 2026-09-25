import numpy as np

from lyri.audio import FPS
from lyri.timing import clamp_ends, enforce_order, extend_ends, fill_gaps


def w(start, end=None):
    return {"start": start, "end": start + 0.2 if end is None and start is not None else end}


def test_enforce_order_drops_backwards_words():
    words = [w(1.0), w(2.0), w(1.5), w(3.0)]
    assert enforce_order(words) == 1
    assert words[2]["start"] is None


def test_fill_gaps_interpolates_between_neighbours():
    words = [w(1.0, 1.5), {"start": None, "end": None}, {"start": None, "end": None}, w(2.5, 3.0)]
    fill_gaps(words)
    assert [round(x["start"], 2) for x in words] == [1.0, 1.5, 2.0, 2.5]
    assert words[1]["conf"] == 0.0


def test_fill_gaps_at_edges():
    words = [{"start": None, "end": None}, w(2.0, 2.4), {"start": None, "end": None}]
    fill_gaps(words)
    assert words[0]["start"] <= words[1]["start"] <= words[2]["start"]


def test_extend_ends_follows_a_held_note_but_not_into_the_next_word():
    rms = np.zeros(int(10 * FPS))
    rms[int(1.0 * FPS) : int(3.0 * FPS)] = 1.0  # singing from 1 s to 3 s
    words = [w(1.0, 1.2), w(2.5, 2.6)]
    extend_ends(words, rms, threshold=0.5)
    assert words[0]["end"] == 2.5  # stops at the next word
    assert abs(words[1]["end"] - 3.0) < 0.05  # holds until the singing stops


def test_clamp_ends():
    words = [w(1.0, 5.0), w(2.0, 2.5)]
    clamp_ends(words)
    assert words[0]["end"] == 2.0
