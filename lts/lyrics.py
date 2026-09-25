"""Lyrics lookup (LRCLIB), parsing, and validation against a Whisper transcript."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
import requests

API = "https://lrclib.net/api"
HEADERS = {"User-Agent": "LyricsTimeStamper/0.1 (local tool)"}

LRC_TIME = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_SECTIONS = r"(?:verse|chorus|pre-?chorus|post-?chorus|hook|bridge|intro|outro|refrain|interlude|instrumental)"
# A header is a bare section name ("Verse 2", "Chorus x2") or a label whose colon follows the
# section name ("Verse 1: Some Artist"). A lyric line that merely starts with "Bridge…" is kept.
SECTION_HEADER = re.compile(
    rf"^\s*{_SECTIONS}\s*\d*\s*(?:[x×]\s*\d+)?\s*(?::.{{0,40}})?$",
    re.I,
)
PAREN_HEADER = re.compile(rf"^\s*\(\s*{_SECTIONS}\b[^)]*\)\s*$", re.I)
BRACKETED = re.compile(r"^\s*\[[^\]]*\]\s*$")
REPEAT_MARK = re.compile(r"\s*[\[(]\s*x\s*\d+\s*[\])]\s*$|\s*[\[(]\s*\d+\s*x\s*[\])]\s*$", re.I)

STOPWORDS = set(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "i",
        "im",
        "i'm",
        "you",
        "your",
        "me",
        "my",
        "we",
        "our",
        "us",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "this",
        "that",
        "what",
        "when",
        "where",
        "so",
        "do",
        "dont",
        "don't",
        "not",
        "no",
        "yes",
        "oh",
        "ooh",
        "ah",
        "yeah",
        "la",
        "na",
        "hey",
        "uh",
        "mm",
        "mmm",
        "whoa",
        "like",
        "just",
        "all",
        "got",
        "get",
        "can",
        "will",
    ]
)


@dataclass
class Lyrics:
    lines: list[str]
    times: list[float] | None  # per-line start times when synced
    source: str
    artist: str = ""
    title: str = ""
    extra: dict = field(default_factory=dict)


# ---------- metadata ----------


def read_tags(path: Path) -> dict:
    try:
        f = mutagen.File(path, easy=True)
    except Exception:
        f = None
    tags = {}
    if f and f.tags:
        for key in ("artist", "title", "album"):
            if f.tags.get(key):
                tags[key] = f.tags[key][0].strip()
    return tags


def guess_from_filename(path: Path) -> dict:
    stem = re.sub(r"[_]+", " ", path.stem)
    stem = re.sub(r"\s*[\[(](official|lyrics?|audio|video|hd|hq|music video)[^\])]*[\])]", "", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return {"artist": artist.strip(), "title": title.strip()}
    return {"title": stem}


# ---------- parsing ----------


def parse_lrc(text: str) -> tuple[list[str], list[float]]:
    entries = []
    for raw in text.splitlines():
        stamps = LRC_TIME.findall(raw)
        if not stamps:
            continue
        body = LRC_TIME.sub("", raw).strip()
        body = re.sub(r"<\d+:\d+(?:\.\d+)?>", "", body)  # enhanced-LRC word tags
        body = re.sub(r"\s+", " ", body).strip()
        for m, s in stamps:
            entries.append((int(m) * 60 + float(s.replace(":", ".")), body))
    entries.sort(key=lambda e: e[0])
    entries = [(t, clean_line(b)) for t, b in entries]
    entries = [(t, b) for t, b in entries if b]
    return [b for _, b in entries], [t for t, _ in entries]


def clean_line(line: str) -> str:
    line = line.strip()
    if not line or BRACKETED.match(line) or PAREN_HEADER.match(line) or SECTION_HEADER.match(line):
        return ""
    return REPEAT_MARK.sub("", line).strip()


def parse_plain(text: str) -> list[str]:
    if LRC_TIME.search(text):
        return parse_lrc(text)[0]
    return [ln for ln in (clean_line(r) for r in text.splitlines()) if ln]


def load_lyrics_file(path: Path) -> Lyrics:
    text = path.read_text(encoding="utf-8")
    if LRC_TIME.search(text):
        lines, times = parse_lrc(text)
        return Lyrics(lines, times, "user-lrc")
    return Lyrics(parse_plain(text), None, "user-text")


# ---------- LRCLIB ----------


def _get(path: str, params: dict):
    try:
        r = requests.get(f"{API}/{path}", params=params, headers=HEADERS, timeout=15)
    except requests.RequestException:
        return None
    return r.json() if r.ok else None


def lrclib_candidates(artist: str | None, title: str, album: str | None, duration: float) -> list[dict]:
    found: dict[int, dict] = {}
    if artist:
        params = {"artist_name": artist, "track_name": title, "duration": round(duration)}
        if album:
            params["album_name"] = album
        hit = _get("get", params)
        if isinstance(hit, dict) and hit.get("id"):
            found[hit["id"]] = hit
        for hit in _get("search", {"track_name": title, "artist_name": artist}) or []:
            found.setdefault(hit["id"], hit)
    for hit in _get("search", {"q": f"{artist} {title}" if artist else title}) or []:
        found.setdefault(hit["id"], hit)
    return [h for h in found.values() if not h.get("instrumental") and (h.get("plainLyrics") or h.get("syncedLyrics"))]


def to_lyrics(hit: dict) -> Lyrics:
    common = dict(
        artist=hit.get("artistName", ""),
        title=hit.get("trackName", ""),
        extra={"lrclib_id": hit["id"], "lrclib_duration": hit.get("duration")},
    )
    if hit.get("syncedLyrics"):
        lines, times = parse_lrc(hit["syncedLyrics"])
        if lines:
            return Lyrics(lines, times, "lrclib-synced", **common)
    return Lyrics(parse_plain(hit["plainLyrics"]), None, "lrclib-plain", **common)


# ---------- validation ----------


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z']+", text.lower().replace("’", "'"))
    return {w.strip("'") for w in words if len(w) >= 3 and w not in STOPWORDS}


def match_score(lyrics_text: str, transcript_text: str) -> float | None:
    """Fraction of the transcript's content words that appear in the lyrics.

    None when the transcript is too sparse to judge.
    """
    heard = content_words(transcript_text)
    if len(heard) < 8:
        return None
    return len(heard & content_words(lyrics_text)) / len(heard)


def find_lyrics(
    audio_path: Path,
    duration: float,
    transcript_text: str,
    artist: str | None = None,
    title: str | None = None,
    log=print,
) -> Lyrics | None:
    meta = {**guess_from_filename(audio_path), **read_tags(audio_path)}
    artist = artist or meta.get("artist")
    title = title or meta.get("title")
    if not title:
        return None
    log(f"lyrics: searching LRCLIB for {artist or '?'} – {title}")

    ranked = []
    for hit in lrclib_candidates(artist, title, meta.get("album"), duration):
        lyr = to_lyrics(hit)
        if not lyr.lines:
            continue
        ddiff = abs((hit.get("duration") or 0) - duration)
        if lyr.times and ddiff > 3:
            # Synced timings from a different edit of the song are worse than none.
            lyr.times, lyr.source = None, "lrclib-plain"
        score = match_score("\n".join(lyr.lines), transcript_text)
        # When too little was heard to verify the text, only trust a tight duration match.
        ok = score >= 0.35 if score is not None else ddiff <= 2
        log(
            f"  candidate #{hit['id']} {hit.get('artistName')} – {hit.get('trackName')} "
            f"({lyr.source}, Δdur={ddiff:.1f}s, match={'n/a' if score is None else f'{score:.2f}'})"
            f"{'' if ok else ' rejected'}"
        )
        if ok:
            # Prefer good text match, then synced, then closest duration.
            ranked.append((round(score or 0.5, 1), lyr.times is not None, -ddiff, lyr))
    if not ranked:
        return None
    ranked.sort(key=lambda r: r[:3], reverse=True)
    return ranked[0][3]
