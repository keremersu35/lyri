"""Brat-style lyric videos: draw each distinct frame once, let ffmpeg repeat it.

A lyric video only changes when a word appears, so a 3-minute song has a few hundred
distinct frames instead of ~5,000. Timing and layout match web/player.html.
"""

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Narrow.ttf",  # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",  # Linux with ttf-mscorefonts
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
]
LINE_HEIGHT = 0.92
LETTER_SPACING = -0.02  # em
LEAD = 0.15  # show a line slightly before its first word
HOLD = 2.5  # max seconds a finished line stays up before an instrumental break
UNSUNG_OPACITY = 0.2  # highlight mode
BOX_W, BOX_H = 0.86, 0.62  # text box as a share of the frame

DEFAULTS = {
    "mode": "reveal",  # "reveal": words appear as sung; "highlight": whole line, sung words solid
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "bg": "#8ace00",
    "fg": "#000000",
    "blur": True,
    "offset_ms": 0,  # positive = lyrics later
    "profile": "default",
}

# iPod classic (6th/7th gen, per Apple's spec sheet): 320x240 screen; plays H.264 Baseline up to
# Level 3.0, <=2.5 Mbps, <=640x480, 30 fps, AAC-LC <=160 kbps 48 kHz. Anything else (e.g. x264's
# default High profile) is refused when syncing.
PROFILES = {
    "default": {
        "ext": "mp4",
        "max_fps": 60,
        "max_size": None,
        "video": ["-crf", "18", "-pix_fmt", "yuv420p"],
        "audio": ["-c:a", "aac", "-b:a", "256k"],
    },
    "ipod": {
        "ext": "m4v",
        "max_fps": 30,
        "max_size": (640, 480),
        "video": ["-profile:v", "baseline", "-level:v", "3.0", "-crf", "20", "-maxrate", "1500k", "-bufsize", "3000k",
                  "-pix_fmt", "yuv420p"],
        "audio": ["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "160k", "-ar", "48000", "-ac", "2"],
    },
}  # fmt: skip

State = tuple[int, int]  # (line index or -1 for a blank frame, words sung)


# ---------- layout ----------


@lru_cache(maxsize=64)
def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError("no Arial/Arial Narrow-like font found; add one to lts.render.FONT_PATHS")


def text_width(word: str, size: int) -> float:
    return font(size).getlength(word) + LETTER_SPACING * size * len(word)


def wrap(words: list[str], size: int, max_w: float) -> list[list[str]]:
    """Greedy word wrap, like the browser's."""
    space = font(size).getlength(" ")
    rows: list[list[str]] = [[]]
    row_w = 0.0
    for w in words:
        ww = text_width(w, size)
        if rows[-1] and row_w + space + ww > max_w:
            rows.append([w])
            row_w = ww
        else:
            row_w += (space if rows[-1] else 0) + ww
            rows[-1].append(w)
    return rows


def fit_size(words: list[str], max_w: float, max_h: float) -> int:
    """Largest font size at which the words wrap into the box."""
    lo, hi = 20, 420
    while hi - lo > 1:
        mid = (lo + hi) // 2
        fits = all(text_width(w, mid) <= max_w for w in words)
        fits = fits and len(wrap(words, mid, max_w)) * mid * LINE_HEIGHT <= max_h
        lo, hi = (mid, hi) if fits else (lo, mid)
    return lo


def hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def draw_state(line: dict | None, n_sung: int, o: dict) -> Image.Image:
    w, h = o["width"], o["height"]
    bg, fg = hex_rgb(o["bg"]), hex_rgb(o["fg"])
    img = Image.new("RGB", (w, h), bg)
    if line is None:
        return img
    all_words = [x["text"].lower() for x in line["words"]]
    max_w = w * BOX_W
    size = fit_size(all_words, max_w, h * BOX_H)  # sized for the whole line so text doesn't jump
    shown = all_words[:n_sung] if o["mode"] == "reveal" else all_words
    if not shown:
        return img
    dim = tuple(round(b + (f - b) * UNSUNG_OPACITY) for f, b in zip(fg, bg, strict=True))
    f = font(size)
    ascent, descent = f.getmetrics()
    lh = size * LINE_HEIGHT
    rows = wrap(shown, size, max_w)
    top = (h - len(rows) * lh) / 2
    space = f.getlength(" ")
    draw = ImageDraw.Draw(img)
    idx = 0
    for r, row in enumerate(rows):
        x = (w - sum(text_width(word, size) for word in row) - space * (len(row) - 1)) / 2
        baseline = top + r * lh + (lh - (ascent + descent)) / 2 + ascent  # CSS half-leading
        for word in row:
            color = fg if idx < n_sung else dim
            for ch in word:  # per character, to apply the letter spacing
                draw.text((x, baseline), ch, font=f, fill=color, anchor="ls")
                x += f.getlength(ch) + LETTER_SPACING * size
            x += space
            idx += 1
    if o["blur"]:
        img = img.filter(ImageFilter.GaussianBlur(max(0.6, size * 0.011)))
    return img


# ---------- timing ----------


def line_at(lines: list[dict], t: float) -> int:
    """Index of the line on screen at time t, or -1 (before the first line / instrumental break)."""
    i = -1
    for k, line in enumerate(lines):
        if line["start"] - LEAD > t:
            break
        i = k
    if i < 0:
        return -1
    nxt = lines[i + 1] if i + 1 < len(lines) else None
    hold_until = lines[i]["end"] + HOLD
    if nxt:
        hold_until = min(nxt["start"] - LEAD, hold_until)
    return i if t <= hold_until else -1


def timeline(doc: dict, fps: int, offset: float = 0.0) -> list[tuple[State, int]]:
    """Run-length encoded [(state, n_frames)] for the whole song."""
    lines = doc["lines"]
    runs: list[list] = []
    for k in range(int(doc["meta"]["duration"] * fps + 0.999)):
        t = round(k / fps - offset, 6)  # 23/10 - 0.3 must be 2.0, not 1.9999999
        i = line_at(lines, t)
        state = (i, sum(1 for w in lines[i]["words"] if w["start"] <= t)) if i >= 0 else (-1, 0)
        if runs and runs[-1][0] == state:
            runs[-1][1] += 1
        else:
            runs.append([state, 1])
    return [(state, count) for state, count in runs]


# ---------- encoding ----------


def render_video(
    work: Path,
    options: dict | None = None,
    progress: Callable[[float], None] | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    """Render work/video-*.mp4 (or .m4v for iPod) from work/lyrics.json; `progress` gets 0..1."""
    doc = json.loads((work / "lyrics.json").read_text())
    o = {**DEFAULTS, **(options or {})}
    prof = PROFILES[o["profile"]]
    o["fps"] = fps = min(o["fps"], prof["max_fps"])
    if prof["max_size"]:
        scale = min(1.0, prof["max_size"][0] / o["width"], prof["max_size"][1] / o["height"])
        o["width"], o["height"] = int(o["width"] * scale), int(o["height"] * scale)
    o["width"], o["height"] = o["width"] // 2 * 2, o["height"] // 2 * 2  # even sizes for yuv420p

    t0 = time.time()
    runs = timeline(doc, fps, o["offset_ms"] / 1000)
    total = sum(count for _, count in runs)
    tag = "ipod-" if o["profile"] == "ipod" else ""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = (work / f"video-{tag}{o['width']}x{o['height']}-{stamp}.{prof['ext']}").resolve()

    with tempfile.TemporaryDirectory() as tmp:
        frames: dict[State, Path] = {}
        for j, (state, _) in enumerate(runs):
            if state not in frames:
                i, sung = state
                path = Path(tmp) / f"{len(frames):05d}.png"
                draw_state(doc["lines"][i] if i >= 0 else None, sung, o).save(path, compress_level=1)
                frames[state] = path
            if progress and j % 10 == 0:
                progress(0.5 * j / len(runs))
        concat = Path(tmp) / "frames.txt"
        with concat.open("w") as fh:
            for state, count in runs:
                fh.write(f"file '{frames[state]}'\nduration {count / fps:.6f}\n")
            fh.write(f"file '{frames[runs[-1][0]]}'\n")  # the concat demuxer needs the last file twice
        log(f"render: {len(frames)} distinct frames for {total} video frames ({time.time() - t0:.1f}s)")

        cmd = [
            "ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats",
            "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(work / doc["meta"]["audio"]),
            "-map", "0:v", "-map", "1:a", "-r", str(fps), "-fps_mode", "cfr",
            # x264's stillimage tune codes repeated frames almost for free: measured 3x faster and
            # 2.5x smaller than h264_videotoolbox at visually lossless quality
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", *prof["video"],
            *prof["audio"], "-shortest", "-movflags", "+faststart", str(out),
        ]  # fmt: skip
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if line.startswith("frame=") and progress:
                progress(0.5 + 0.5 * min(1.0, int(line.split("=")[1]) / total))
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed: " + proc.stderr.read()[-800:])
    log(f"video -> {out} ({time.time() - t0:.1f}s)")
    return out
