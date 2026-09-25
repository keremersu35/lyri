"""Word-timestamped transcription with Whisper (MLX, Apple Silicon)."""

import mlx_whisper

# Phrases Whisper emits on music/silence (learned from YouTube outros).
HALLUCINATIONS = {
    "thank you",
    "thanks for watching",
    "thank you for watching",
    "you",
    "bye",
    "subtitles by the amara.org community",
    "please subscribe",
    "music",
}

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large": "mlx-community/whisper-large-v3-mlx",
}


def transcribe(vocals_path, model: str = "turbo", language: str | None = None) -> dict:
    res = mlx_whisper.transcribe(
        str(vocals_path),
        path_or_hf_repo=MODELS[model],
        language=language,
        word_timestamps=True,
        # Songs repeat a lot; conditioning on previous text makes Whisper loop.
        condition_on_previous_text=False,
        hallucination_silence_threshold=2.0,
        verbose=None,
    )
    segments = []
    for seg in res["segments"]:
        # Drop segments Whisper itself thinks are silence/hallucination.
        if seg["no_speech_prob"] > 0.6 and seg["avg_logprob"] < -1.0:
            continue
        words = [
            {"word": w["word"].strip(), "start": w["start"], "end": w["end"], "prob": w["probability"]}
            for w in seg.get("words", [])
            if w["word"].strip()
        ]
        text = " ".join(w["word"] for w in words)
        norm = text.lower().strip(" .!?,")
        if norm in HALLUCINATIONS and min(w["prob"] for w in words) < 0.5:
            continue
        if words:
            segments.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
    return {"language": res["language"], "model": model, "segments": segments}
