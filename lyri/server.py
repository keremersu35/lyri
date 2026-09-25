"""Local web app: upload a song, process it, render videos, watch progress."""

import json
import queue
import re
import threading
import time
import traceback
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lyri.pipeline import run, slugify
from lyri.render import render_video

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
UPLOADS = ROOT / "uploads"
APP_DIR = ROOT / "web" / "app"
AUDIO_EXT = re.compile(r"\.(mp3|m4a|wav|flac|ogg|aac|opus|webm|mp4)$", re.I)
HEX = r"^#[0-9a-fA-F]{6}$"


@dataclass
class Job:
    id: str
    kind: str  # "process" | "video"
    slug: str
    status: str = "queued"  # queued | running | done | error
    stage: str = "queued"
    frac: float | None = None
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: str | None = None  # output file name for video jobs
    created: float = field(default_factory=time.time)

    def log(self, msg: str) -> None:
        print(f"[{self.id}] {msg}")
        self.logs = [*self.logs, msg][-200:]


jobs: dict[str, Job] = {}
work_queue: queue.Queue[tuple[Job, Callable[[Job], None]]] = queue.Queue()


def worker() -> None:
    """Run jobs one at a time: demucs, Whisper and the aligner all want the whole GPU."""
    while True:
        job, fn = work_queue.get()
        job.status = "running"
        try:
            fn(job)
            job.status, job.stage, job.frac = "done", "done", 1.0
        except Exception as e:  # surface any failure to the UI
            job.log(traceback.format_exc())
            job.status, job.error = "error", str(e) or e.__class__.__name__


def enqueue(kind: str, slug: str, fn: Callable[[Job], None]) -> Job:
    job = Job(id=uuid.uuid4().hex[:10], kind=kind, slug=slug)
    jobs[job.id] = job
    work_queue.put((job, fn))
    return job


def song_info(slug: str) -> dict:
    work = OUT / slug
    path = work / "lyrics.json"
    if not path.is_file():
        raise HTTPException(404, "song not processed")
    doc = json.loads(path.read_text())
    words = [w for line in doc["lines"] for w in line["words"]]
    videos = sorted([*work.glob("video-*.mp4"), *work.glob("video-*.m4v")], key=lambda p: -p.stat().st_mtime)
    return {
        "slug": slug,
        "meta": doc["meta"],
        "lines": len(doc["lines"]),
        "words": len(words),
        "low_confidence": sum(w["conf"] < 0.2 for w in words),
        "preview": [[w["text"] for w in line["words"]] for line in doc["lines"][:8]],
        "videos": [v.name for v in videos],
        "updated": path.stat().st_mtime,
    }


app = FastAPI(title="Lyri")


@app.get("/")
def index():
    return FileResponse(APP_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.post("/api/process")
async def process(
    audio: UploadFile,
    lyrics: Annotated[str, Form()] = "",
    artist: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
):
    name = Path(audio.filename or "song.mp3").name
    if not AUDIO_EXT.search(name):
        raise HTTPException(400, "unsupported audio format")
    upload_dir = UPLOADS / uuid.uuid4().hex[:8]
    upload_dir.mkdir(parents=True)
    song = upload_dir / name
    with song.open("wb") as f:
        while chunk := await audio.read(1 << 20):
            f.write(chunk)
    lyrics_file = None
    if lyrics.strip():
        lyrics_file = upload_dir / "lyrics.txt"
        lyrics_file.write_text(lyrics.strip() + "\n", encoding="utf-8")

    def task(job: Job) -> None:
        def stage(name: str, frac: float | None = None) -> None:
            job.stage, job.frac = name, frac

        run(song, OUT, artist or None, title or None, lyrics_file, log=job.log, stage=stage)

    job = enqueue("process", slugify(song.stem), task)
    return {"job": job.id, "slug": job.slug}


class VideoRequest(BaseModel):
    slug: str
    width: int = Field(1080, ge=240, le=3840)
    height: int = Field(1920, ge=240, le=3840)
    fps: int = Field(30, ge=12, le=60)
    bg: str = Field("#8ace00", pattern=HEX)
    fg: str = Field("#000000", pattern=HEX)
    mode: str = Field("reveal", pattern="^(reveal|highlight)$")
    blur: bool = True
    offset_ms: int = Field(0, ge=-1000, le=1000)
    profile: str = Field("default", pattern="^(default|ipod)$")


@app.post("/api/video")
def video(req: VideoRequest):
    song_info(req.slug)  # 404 if missing
    options = req.model_dump(exclude={"slug"})

    def task(job: Job) -> None:
        def progress(frac: float) -> None:
            job.frac = frac

        job.stage = "render"
        job.result = render_video(OUT / req.slug, options, progress=progress, log=job.log).name

    return {"job": enqueue("video", req.slug, task).id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    data = asdict(job)
    data["logs"] = job.logs[-30:]
    data["queue_position"] = sum(1 for j in jobs.values() if j.status == "queued" and j.created < job.created)
    return data


@app.get("/api/songs")
def songs():
    infos = []
    for path in OUT.glob("*/lyrics.json"):
        try:
            info = song_info(path.parent.name)
        except (HTTPException, OSError, ValueError, KeyError):
            continue  # half-written or foreign folder
        info.pop("preview")
        infos.append(info)
    return sorted(infos, key=lambda s: -s["updated"])


@app.get("/api/songs/{slug}")
def song(slug: str):
    return song_info(slug)


OUT.mkdir(exist_ok=True)
app.mount("/out", StaticFiles(directory=OUT), name="out")
app.mount("/app", StaticFiles(directory=APP_DIR), name="app")


def serve_app(port: int = 8700) -> None:
    import uvicorn

    threading.Thread(target=worker, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Lyri Studio at {url}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
