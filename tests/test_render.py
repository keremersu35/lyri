import pytest

from lyri import render
from lyri.render import HOLD, LEAD, line_at, timeline

LINES = [
    {"start": 2.0, "end": 3.0, "words": [{"text": "one", "start": 2.0}, {"text": "two", "start": 2.5}]},
    {"start": 10.0, "end": 11.0, "words": [{"text": "three", "start": 10.0}]},
]


def test_line_at_lead_hold_and_breaks():
    assert line_at(LINES, 1.0) == -1
    assert line_at(LINES, 2.0 - LEAD) == 0  # shown slightly before its first word
    assert line_at(LINES, 3.0 + HOLD - 0.01) == 0
    assert line_at(LINES, 3.0 + HOLD + 0.1) == -1  # cleared during the instrumental break
    assert line_at(LINES, 10.5) == 1


def test_timeline_run_length_and_offset():
    doc = {"meta": {"duration": 12.0}, "lines": LINES}
    runs = timeline(doc, fps=10)
    assert sum(n for _, n in runs) == 120
    states = [s for s, _ in runs]
    assert states[:4] == [(-1, 0), (0, 0), (0, 1), (0, 2)]
    first_word = lambda r: sum(n for _, n in r[: [s for s, _ in r].index((0, 1))])  # noqa: E731
    assert first_word(timeline(doc, fps=10, offset=0.3)) == first_word(runs) + 3


def test_draw_state_size_and_blank_frame():
    pytest.importorskip("PIL")
    try:
        render.font(40)
    except FileNotFoundError:
        pytest.skip("no Arial-like font on this machine")
    opts = {**render.DEFAULTS, "width": 320, "height": 240}
    blank = render.draw_state(None, 0, opts)
    assert blank.size == (320, 240) and len(blank.getcolors()) == 1
    frame = render.draw_state(LINES[0], 1, opts)
    assert len(frame.getcolors(10_000)) > 1  # some text was drawn
