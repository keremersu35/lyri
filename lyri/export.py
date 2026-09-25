"""Writers for the aligned lyrics: JSON (canonical), enhanced LRC, SRT, ASS karaoke."""

import json
from pathlib import Path


def _lrc_ts(t: float) -> str:
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m):02d}:{s:05.2f}"


def _srt_ts(t: float) -> str:
    ms = int(round(max(t, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_ts(t: float) -> str:
    cs = int(round(max(t, 0.0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_json(doc: dict, path: Path) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def write_lrc(doc: dict, path: Path) -> None:
    meta = doc["meta"]
    out = [f"[ar:{meta.get('artist', '')}]", f"[ti:{meta.get('title', '')}]"]
    for line in doc["lines"]:
        words = " ".join(f"<{_lrc_ts(w['start'])}> {w['text']}" for w in line["words"])
        out.append(f"[{_lrc_ts(line['start'])}] {words} <{_lrc_ts(line['end'])}>")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_srt(doc: dict, path: Path) -> None:
    blocks = [
        f"{i}\n{_srt_ts(line['start'])} --> {_srt_ts(line['end'])}\n{line['text']}\n"
        for i, line in enumerate(doc["lines"], 1)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")


# The ASS spec requires these exact one-line Format/Style declarations.
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Brat,Arial Narrow,110,&H00000000,&H99000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(doc: dict, path: Path) -> None:
    """Karaoke subtitles: each word fills in as it is sung ({\\kf})."""
    events = []
    for line in doc["lines"]:
        parts, cursor = [], line["start"]
        for w in line["words"]:
            if w["start"] > cursor:
                parts.append(f"{{\\k{round((w['start'] - cursor) * 100)}}}")
            parts.append(f"{{\\kf{max(1, round((w['end'] - w['start']) * 100))}}}{w['text'].lower()} ")
            cursor = max(cursor, w["end"])
        events.append(
            f"Dialogue: 0,{_ass_ts(line['start'])},{_ass_ts(line['end'])},Brat,,0,0,0,,{''.join(parts).rstrip()}"
        )
    path.write_text(ASS_HEADER + "\n".join(events) + "\n", encoding="utf-8")


def write_all(doc: dict, work: Path) -> None:
    write_json(doc, work / "lyrics.json")
    write_lrc(doc, work / "lyrics.lrc")
    write_srt(doc, work / "lyrics.srt")
    write_ass(doc, work / "lyrics.ass")
