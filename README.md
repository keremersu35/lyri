# LyricsTimeStamper

Word-level timestamped lyrics for any song, plus Brat-style lyric videos — computed locally on an Apple Silicon Mac.

Give it an MP3 and it returns every word's start and end time as JSON, enhanced LRC, SRT and ASS karaoke,
a browser player, and a vertical (or square, or iPod classic) MP4.

**[Live demo →](https://github.com/)** *(GitHub Pages; update this link after the first deploy)*

## Quick start

Requirements: Apple Silicon Mac (M1 or newer), [`uv`](https://docs.astral.sh/uv/) and `ffmpeg`.

```bash
brew install uv ffmpeg
git clone https://github.com/<you>/LyricsTimeStamper && cd LyricsTimeStamper
uv run lts app            # opens the web app at http://127.0.0.1:8700
```

The first run downloads the models (a few GB) into the Hugging Face cache.

### Command line

```bash
uv run lts process "Artist - Title.mp3"                 # -> out/<song>/lyrics.json (+ .lrc .srt .ass, player)
uv run lts process song.mp3 --lyrics lyrics.txt          # use your own lyrics (.txt or .lrc)
uv run lts serve out/<song>                              # Brat player in the browser
uv run lts video out/<song>                              # 1080x1920 MP4
uv run lts video out/<song> --size 1080x1080 --mode highlight --bg "#ffffff" --offset 80
uv run lts video out/<song> --ipod                       # iPod classic: 320x240 H.264 Baseline .m4v
```

`process` options: `--artist/--title` when tags and file name don't say, `--no-separate` for a cappella input.
`--offset` (and the app's *Sync* slider) shifts lyrics in milliseconds, positive = later.

## How it works

1. **Vocal separation** — Demucs `htdemucs` splits vocals from the backing track. The stems tell us whether
   anyone sings at all (instrumentals are reported, not hallucinated) and where the instrumental breaks are.
2. **Lyrics text** — your pasted lyrics; otherwise [LRCLIB](https://lrclib.net) by tags or the
   `Artist - Title` file name. A candidate is accepted only if its words match what Whisper
   (`large-v3-turbo`, via mlx-whisper) hears in the vocals, which rejects wrong songs. Nothing found?
   Whisper `large-v3` transcribes the song, ignoring text it invents over instrumental parts.
3. **Forced alignment** — a CTC acoustic model trained on songs scores every 20 ms frame of the mix
   (computed in parallel with separation), and a Viterbi search places each character of the known text.
   Frames where nobody sings are penalised so words can't drift into breaks. Each word's `start` is its
   first vowel — when a listener hears it — and `onset` its first consonant.
4. **Clean-up** — out-of-order words are re-timed, unalignable ones interpolated, word ends stretched over
   held notes using vocal energy. Sung passages missing from online lyrics are added from the transcript
   (marked `"heard": true`).
5. **Video** — a lyric video only changes when a word appears, so each distinct frame is drawn once (Pillow)
   and x264's `stillimage` tune repeats it: a 2-minute 1080×1920 video renders in about 12 s.

## Accuracy

Word onsets against hand annotations on English [JamendoLyrics](https://huggingface.co/datasets/jamendolyrics/jamendolyrics)
songs (first 3 songs, lyrics given):

| | LibriSpeech wav2vec2 (first version) | now |
|---|---|---|
| Mean onset error | 0.226 s | **0.088 s** |
| Words within 0.3 s | 90.4 % | **97.7 %** |
| Words off by more than 1 s | 50 | **13** |
| Vocal energy rise after the shown word start | +38 ms | **+17 ms** |

Reproduce with `uv run python bench/jamendo.py --songs 3` (drop `--songs` for all 20). The dataset marks the
first consonant, while words are now shown at their first vowel, so the displayed timing trades a few ms of
annotation error for a better felt sync (last row). `bench/synthetic.py` checks the machinery against speech
placed at exactly known times.

## Output format

`out/<song>/lyrics.json`:

```json
{
  "meta": {"title": "…", "artist": "…", "duration": 193.0, "audio": "song.mp3",
           "lyrics_source": "user-text | lrclib-synced | lrclib-plain | transcription", "low_confidence_words": 5},
  "lines": [{"start": 18.7, "end": 21.4, "text": "…",
             "words": [{"text": "…", "start": 18.72, "onset": 18.7, "end": 19.1, "conf": 0.93}]}]
}
```

`conf` is the aligner's mean character probability; below 0.2 is worth a look. Instrumental tracks get
`"instrumental": true` and no lines.

## Project layout

```
lts/            the Python package
  pipeline.py     orchestration: stems -> text -> alignment -> exports
  separate.py     Demucs             transcribe.py   Whisper (MLX)       lyrics.py   LRCLIB, parsing, validation
  aligner.py      CTC model          ctc.py          Viterbi, text norm  lines.py    line-level strategies
  vocals.py       vocal activity     timing.py       word-timing fixes   export.py   JSON/LRC/SRT/ASS
  render.py       video renderer     server.py       web app API         cli.py      `lts` command
web/app/        the web app (plain HTML/CSS/JS, no build step)
web/player.html the Brat player (copied next to every processed song)
site/           GitHub Pages: landing page and demo (built by scripts/build_site.sh)
bench/          accuracy benchmarks        tests/  fast unit tests (no models)
```

Development: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`.

## Limitations

- **Apple Silicon only** for now (mlx-whisper, MPS). A Linux/CUDA port would swap in faster-whisper.
- **English** alignment. Other languages are detected and warned about.
- **Alignment model availability.** The singing model,
  [`mrfakename/w2v-bert-2.0-music-lyrics-ctc`](https://huggingface.co/mrfakename/w2v-bert-2.0-music-lyrics-ctc)
  (MIT), has been removed from Hugging Face. If it is in your local cache it is used; otherwise the pipeline
  falls back to `facebook/wav2vec2-large-960h-lv60-self` on the vocal stem (the "first version" column above).
  Point `LTS_ALIGN_MODEL` at a mirror or local folder to use the singing model.
- Video text uses Arial Narrow from macOS; it is not bundled.

## Credits and licenses

MIT — see [LICENSE](LICENSE). Built on [Demucs](https://github.com/facebookresearch/demucs) (MIT),
[Whisper](https://github.com/openai/whisper) via [mlx-whisper](https://github.com/ml-explore/mlx-examples) (MIT),
[Transformers](https://github.com/huggingface/transformers) (Apache-2.0), [LRCLIB](https://lrclib.net),
FastAPI, Pillow and FFmpeg. Demo song: "Feel (Stripped)" by Cortéz, CC BY via Jamendo
([details](site/demo/ATTRIBUTION.md)).

Most commercial songs and lyrics are copyrighted. The tool processes files you already have, on your own
machine; sharing the results is up to you and the rights holders.
