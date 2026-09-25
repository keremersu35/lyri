"""End to end: song file -> vocal stems -> lyrics text -> word timings -> exports."""

import json
import re
import shutil
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from lts import export
from lts.aligner import Aligner
from lts.audio import HOP, load_audio, probe_duration
from lts.ctc import normalize_word
from lts.lines import (
    add_missing_passages,
    align_global,
    align_windowed,
    drop_unsung,
    repair_with_synced,
    transcript_lyrics,
)
from lts.lyrics import find_lyrics, load_lyrics_file
from lts.separate import separate_vocals
from lts.timing import clamp_ends, enforce_order, extend_ends, fill_gaps
from lts.transcribe import transcribe
from lts.vocals import apply_vocal_mask, vocal_activity, vocal_envelope, vocal_mask

PLAYER = Path(__file__).resolve().parent.parent / "web" / "player.html"
NO_TRANSCRIPT = {"language": "en", "model": None, "segments": []}

Log = Callable[[str], None]
Stage = Callable[..., None]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "song"


def cached_json(path: Path, compute):
    if path.exists():
        return json.loads(path.read_text())
    data = compute()
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data


def _mix_emissions(audio_path: Path) -> tuple[Aligner, np.ndarray]:
    aligner = Aligner()
    return aligner, aligner.emissions(load_audio(audio_path))


def run(
    audio_path: Path,
    out_root: Path,
    artist: str | None = None,
    title: str | None = None,
    lyrics_file: Path | None = None,
    separate: bool = True,
    log: Log = print,
    stage: Stage = lambda name, frac=None: None,
) -> Path:
    """Process one song into out_root/<slug>/. Returns that folder.

    `stage(name, frac)` reports progress for UIs: separate, transcribe, lyrics, align.
    """
    t0 = time.time()
    audio_path = audio_path.resolve()
    work = out_root / slugify(audio_path.stem)
    work.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(audio_path)
    song_copy = work / f"song{audio_path.suffix.lower()}"
    if not song_copy.exists():
        shutil.copy2(audio_path, song_copy)
    meta = {
        "file": audio_path.name,
        "audio": song_copy.name,
        "duration": round(duration, 3),
        "title": audio_path.stem.replace("_", " "),
    }
    log(f"== {audio_path.name} ({duration:.0f}s) -> {work}")

    # The aligner works on the full mix, so its emissions are computed while demucs runs.
    pool = ThreadPoolExecutor(1)
    emissions_job = pool.submit(_mix_emissions, audio_path)
    pool.shutdown(wait=False)

    # 1. stems ---------------------------------------------------------------------------
    mask = None
    if separate:
        log("1/4 separating vocals (demucs)…")
        stage("separate", 0.0)
        vocals = separate_vocals(audio_path, work, progress=lambda f: stage("separate", f))
        vocal_audio, inst_audio = load_audio(vocals), load_audio(work / "instrumental.wav")
        activity = vocal_activity(vocal_audio, inst_audio)
        log(f"vocals: singing detected in {activity:.0%} of the track")
        if activity < 0.03 and not lyrics_file:
            log("vocals: track looks instrumental -> no lyrics to time")
            return _finish(work, {"version": 1, "meta": {**meta, "instrumental": True}, "lines": []}, t0, log)
        mask = vocal_mask(vocal_audio, inst_audio, len(vocal_audio) // HOP)
    else:
        vocals, vocal_audio = audio_path, load_audio(audio_path)

    # 2. transcript: verifies online lyrics, fills gaps in them, or is the text itself -----
    stage("transcribe")
    if lyrics_file:
        transcript = NO_TRANSCRIPT  # measured: pasted lyrics align better without Whisper's hints
    else:
        log("2/4 transcribing vocals (whisper turbo)…")
        transcript = cached_json(work / "transcript.json", lambda: transcribe(vocals, "turbo"))
        if transcript["language"] != "en":
            log(f"warning: detected language '{transcript['language']}'; the aligner is English-only")

    # 3. lyrics text ------------------------------------------------------------------------
    log("3/4 getting lyrics text…")
    stage("lyrics")
    if lyrics_file:
        lyr = load_lyrics_file(Path(lyrics_file))
    else:
        heard = " ".join(s["text"] for s in transcript["segments"])
        lyr = find_lyrics(audio_path, duration, heard, artist, title, log=log)
    if lyr is None:
        log("lyrics: none found online -> transcribing with whisper large-v3 for the best text")
        transcript = cached_json(
            work / "transcript_large.json", lambda: transcribe(vocals, "large", language=transcript["language"])
        )
        lyr = transcript_lyrics(drop_unsung(transcript, mask, log))
    log(f"lyrics: using {lyr.source}, {len(lyr.lines)} lines")

    # 4. alignment --------------------------------------------------------------------------
    log("4/4 aligning words (CTC forced alignment)…")
    stage("align")
    aligner, emission = emissions_job.result()
    if aligner.wants_vocals:
        log(f"align: using {aligner.model_id} on the vocal stem (singing model unavailable)")
        emission = aligner.emissions(vocal_audio)
    if mask is not None:
        emission = apply_vocal_mask(emission, mask, aligner.blank)
    texts = list(lyr.lines)
    display = [line.split() for line in texts]
    norm = [[normalize_word(w) for w in line] for line in display]
    inserted: set[int] = set()
    if lyr.source == "transcription":
        timed = align_windowed(aligner, emission, norm, lyr.times, lyr.extra["ends"])
    else:
        timed = align_global(aligner, emission, norm)
        if lyr.times:
            timed = repair_with_synced(aligner, emission, norm, timed, lyr.times, duration, log)
        texts, display, timed, inserted = add_missing_passages(
            aligner, emission, texts, display, timed, transcript, mask, log
        )

    words = [
        {"text": d, **(t or {"start": None, "end": None})}
        for d_line, t_line in zip(display, timed, strict=True)
        for d, t in zip(d_line, t_line, strict=True)
    ]
    if dropped := enforce_order(words):
        log(f"align: re-timed {dropped} out-of-order word(s)")
    fill_gaps(words)
    extend_ends(words, *vocal_envelope(vocal_audio))
    clamp_ends(words)

    lines, i = [], 0
    for li, (text, d_line) in enumerate(zip(texts, display, strict=True)):
        ws = words[i : i + len(d_line)]
        i += len(d_line)
        if not ws:
            continue
        for w in ws:
            w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)
            w["onset"] = round(min(w.get("onset", w["start"]), w["start"]), 3)
            w["conf"] = round(w.get("conf", 0.0), 3)
        line = {"start": ws[0]["start"], "end": ws[-1]["end"], "text": text, "words": ws}
        if li in inserted:
            line["heard"] = True  # not in the lyrics text; transcribed from the audio
        lines.append(line)

    meta.update(
        title=lyr.title or meta["title"],
        artist=lyr.artist,
        language=transcript["language"],
        lyrics_source=lyr.source,
        low_confidence_words=sum(w["conf"] < 0.2 for line in lines for w in line["words"]),
        **{k: v for k, v in lyr.extra.items() if k != "ends"},
    )
    return _finish(work, {"version": 1, "meta": meta, "lines": lines}, t0, log)


def _finish(work: Path, doc: dict, t0: float, log: Log) -> Path:
    export.write_all(doc, work)
    if PLAYER.exists():
        shutil.copy2(PLAYER, work / "index.html")
    n_words = sum(len(line["words"]) for line in doc["lines"])
    log(
        f"done in {time.time() - t0:.0f}s: {len(doc['lines'])} lines, {n_words} words "
        f"({doc['meta'].get('low_confidence_words', 0)} low-confidence) -> {work / 'lyrics.json'}"
    )
    return work
