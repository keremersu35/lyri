from lyri.lyrics import clean_line, match_score, parse_lrc, parse_plain

LRC = """[ar:Nobody]
[ti:Test Tune]
[00:12.50]first line here
[00:15.00][01:40.25]chorus comes back
[00:18.2]<00:18.20> enhanced <00:18.90> words
[00:20.00]
"""


def test_parse_lrc_expands_repeats_and_sorts():
    lines, times = parse_lrc(LRC)
    assert lines == ["first line here", "chorus comes back", "enhanced words", "chorus comes back"]
    assert times == [12.5, 15.0, 18.2, 100.25]


def test_clean_line_drops_section_headers_and_repeat_marks():
    assert clean_line("[Chorus]") == ""
    assert clean_line("Verse 2:") == ""
    assert clean_line("(Pre-Chorus)") == ""
    assert clean_line("running in circles (x2)") == "running in circles"
    assert clean_line("keep (this) part") == "keep (this) part"


def test_parse_plain():
    text = "[Intro]\nhello paper moon\n\n[Verse 1]\nquiet river song\n"
    assert parse_plain(text) == ["hello paper moon", "quiet river song"]


def test_match_score():
    lyrics = "paper lanterns drifting over silver water\nwhisper something golden to the morning"
    heard_right = "paper lanterns drifting silver water whisper golden morning something"
    heard_wrong = "engines roaring highway midnight concrete neon thunder rolling"
    assert match_score(lyrics, heard_right) > 0.8
    assert match_score(lyrics, heard_wrong) < 0.2
    assert match_score(lyrics, "oh yeah") is None  # too little heard to judge


def test_lines_starting_with_a_section_word_are_lyrics():
    assert clean_line("Bridge over the quiet water") == "Bridge over the quiet water"
    assert clean_line("Hook me in again") == "Hook me in again"
    assert clean_line("Chorus x2") == ""
    assert clean_line("Verse 1: Some Artist:") == ""
