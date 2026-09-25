import json

from lyri.export import _ass_ts, _lrc_ts, _srt_ts, write_all

DOC = {
    "meta": {"artist": "Nobody", "title": "Test Tune"},
    "lines": [
        {"start": 1.0, "end": 2.0, "text": "hello there",
         "words": [{"text": "hello", "start": 1.0, "end": 1.4}, {"text": "there", "start": 1.5, "end": 2.0}]},
    ],
}  # fmt: skip


def test_timestamp_formats():
    assert _lrc_ts(65.432) == "01:05.43"
    assert _srt_ts(3661.5) == "01:01:01,500"
    assert _ass_ts(61.25) == "0:01:01.25"


def test_write_all(tmp_path):
    write_all(DOC, tmp_path)
    assert json.loads((tmp_path / "lyrics.json").read_text())["meta"]["title"] == "Test Tune"
    lrc = (tmp_path / "lyrics.lrc").read_text()
    assert "[00:01.00] <00:01.00> hello <00:01.50> there <00:02.00>" in lrc
    assert "00:00:01,000 --> 00:00:02,000" in (tmp_path / "lyrics.srt").read_text()
    assert "{\\kf40}hello" in (tmp_path / "lyrics.ass").read_text()
