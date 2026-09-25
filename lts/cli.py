"""Command line: `lts app`, `lts process`, `lts video`, `lts serve`."""

import argparse
import contextlib
import functools
import http.server
import webbrowser
from pathlib import Path


def serve(directory: Path, port: int) -> None:
    """Serve a processed song folder (its index.html is the Brat player)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        print(f"serving {directory} at {url} (ctrl+c to stop)")
        webbrowser.open(url)
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()


def parse_size(value: str) -> tuple[int, int]:
    try:
        w, h = (int(x) for x in value.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1080x1920") from None
    return w, h


def main() -> None:
    ap = argparse.ArgumentParser(prog="lts", description="Word-level timestamped lyrics for any song.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("app", help="open the web app (upload, process, render videos)")
    a.add_argument("--port", type=int, default=8700)

    p = sub.add_parser("process", help="extract timestamped lyrics from audio files")
    p.add_argument("songs", nargs="+", type=Path)
    p.add_argument("--artist")
    p.add_argument("--title")
    p.add_argument("--lyrics", type=Path, help="use this .txt/.lrc instead of searching online")
    p.add_argument("--out", type=Path, default=Path("out"))
    p.add_argument("--no-separate", action="store_true", help="skip demucs (a cappella input)")
    p.add_argument("--open", action="store_true", help="open the player when done")

    v = sub.add_parser("video", help="render a Brat-style lyric video for a processed song")
    v.add_argument("dir", type=Path)
    v.add_argument("--mode", choices=["reveal", "highlight"], default="reveal")
    v.add_argument("--size", type=parse_size, default=(1080, 1920), help="WIDTHxHEIGHT")
    v.add_argument("--fps", type=int, default=30)
    v.add_argument("--bg", default="#8ace00")
    v.add_argument("--fg", default="#000000")
    v.add_argument("--no-blur", action="store_true")
    v.add_argument("--offset", type=int, default=0, help="shift lyrics by N ms (positive = later)")
    v.add_argument("--ipod", action="store_true", help="iPod classic: 320x240 H.264 Baseline .m4v")

    s = sub.add_parser("serve", help="open the Brat player for a processed song")
    s.add_argument("dir", type=Path)
    s.add_argument("--port", type=int, default=8765)

    args = ap.parse_args()
    # heavy imports (torch, transformers) only for the commands that need them
    if args.cmd == "app":
        from lts.server import serve_app

        serve_app(args.port)
    elif args.cmd == "process":
        from lts.pipeline import run

        if len(args.songs) > 1 and (args.artist or args.title or args.lyrics):
            ap.error("--artist/--title/--lyrics only make sense with a single song")
        for song in args.songs:
            work = run(song, args.out, args.artist, args.title, args.lyrics, separate=not args.no_separate)
        if args.open:
            serve(work, 8765)
    elif args.cmd == "video":
        from lts.render import render_video

        w, h = (320, 240) if args.ipod else args.size
        options = {
            "mode": args.mode,
            "width": w,
            "height": h,
            "fps": args.fps,
            "bg": args.bg,
            "fg": args.fg,
            "blur": not args.no_blur,
            "offset_ms": args.offset,
            "profile": "ipod" if args.ipod else "default",
        }
        render_video(args.dir, options)
    elif args.cmd == "serve":
        serve(args.dir, args.port)
