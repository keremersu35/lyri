"""Word timings from a CTC acoustic model: emissions for the whole track, then forced alignment."""

import os

import numpy as np
import torch
from transformers import AutoModelForCTC, AutoProcessor
from transformers.utils import logging as hf_logging

from lyri.audio import FPS, HOP, SR
from lyri.ctc import token_frames, viterbi

# w2v-BERT 2.0 fine-tuned on song lyrics (MIT). On JamendoLyrics it halved the >1 s errors of the
# LibriSpeech wav2vec2 model, and works on the full mix. Its Hugging Face repo has since been
# taken down, so it loads from the local cache when present; set LYRI_ALIGN_MODEL to a mirror or a
# local folder to use it elsewhere.
SINGING_MODEL = "mrfakename/w2v-bert-2.0-music-lyrics-ctc"
# English speech model (Apache-2.0), always downloadable. Works on the separated vocals.
SPEECH_MODEL = "facebook/wav2vec2-large-960h-lv60-self"
CHUNK_S, CONTEXT_S = 20.0, 2.0  # model input windows (it accepts up to ~30 s)
# CTC fires a character slightly after its acoustic onset.
ONSET_LAG = 0.04
# A stray late character spike must not stretch a word across an instrumental break;
# genuinely held notes are recovered afterwards from vocal energy (timing.extend_ends).
MAX_WORD_S = 2.5
# Words are shown at their first vowel: listeners hear a sung word arrive with its vowel,
# not its first consonant (measured: vocal energy rises ~40 ms after the consonant onset).
MAX_VOWEL_DELAY = 0.25


def _load(model_id: str):
    """Load from the Hub, falling back to the local cache (the Hub may be offline or the repo gone)."""
    for local_only in (False, True):
        try:
            processor = AutoProcessor.from_pretrained(model_id, local_files_only=local_only)
            return processor, AutoModelForCTC.from_pretrained(model_id, local_files_only=local_only)
        except OSError:
            continue
    return None


class Aligner:
    def __init__(self, device: str | None = None, fp16: bool = True):
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.dtype = torch.float16 if fp16 and self.device != "cpu" else torch.float32
        hf_logging.set_verbosity_error()
        override = os.environ.get("LYRI_ALIGN_MODEL")
        for model_id in [override] if override else [SINGING_MODEL, SPEECH_MODEL]:
            if loaded := _load(model_id):
                break
        else:
            raise RuntimeError(f"could not load an alignment model (tried {override or SINGING_MODEL})")
        self.model_id = model_id
        # the speech model was trained on clean speech: feed it the vocal stem, not the mix
        self.wants_vocals = model_id == SPEECH_MODEL
        self.processor, model = loaded
        self.model = model.to(self.device, self.dtype).eval()
        self.vocab = self.processor.tokenizer.get_vocab()
        self.blank = self.vocab["<blank>"] if "<blank>" in self.vocab else self.vocab["<pad>"]
        self.sep = self.vocab["|"]
        self.vowels = {i for c, i in self.vocab.items() if c.lower() in "aeiouy"}

    @torch.inference_mode()
    def emissions(self, audio: np.ndarray) -> np.ndarray:
        """Frame log-probabilities (T, V) for the whole track, computed in overlapping chunks."""
        n_frames = len(audio) // HOP
        out = np.zeros((n_frames, len(self.vocab)), np.float32)
        chunk, ctx = int(CHUNK_S * SR), int(CONTEXT_S * SR)
        for s in range(0, len(audio), chunk):
            e = min(s + chunk, len(audio))
            ws, we = max(0, s - ctx), min(len(audio), e + ctx)
            inputs = self.processor(audio[ws:we], sampling_rate=SR, return_tensors="pt")
            inputs = {k: v.to(self.device, self.dtype if v.is_floating_point() else v.dtype) for k, v in inputs.items()}
            logp = torch.log_softmax(self.model(**inputs).logits[0].float(), -1).cpu().numpy()
            f0, f1 = s // HOP, min(e // HOP, n_frames)
            off = f0 - ws // HOP
            take = logp[off : off + (f1 - f0)]
            out[f0 : f0 + len(take)] = take
        return out

    def tokenize(self, words: list[str]) -> tuple[list[int], list[tuple[int, int]]]:
        """Token ids for the words joined by '|', plus each word's [start, end) token range."""
        tokens: list[int] = []
        spans = []
        for i, w in enumerate(words):
            if i:
                tokens.append(self.sep)
            start = len(tokens)
            for c in w:
                tok = self.vocab.get(c, self.vocab.get(c.lower()))
                if tok is not None:
                    tokens.append(tok)
            spans.append((start, len(tokens)))
        return tokens, spans

    def align(self, emission: np.ndarray, words: list[str], frame_offset: int = 0) -> list[dict | None]:
        """Align normalized words inside `emission`; per-word timing, or None when unalignable.

        Each timing has `start` (first vowel, when the word is heard), `onset` (first
        consonant), `end` and `conf` (mean character probability).
        """
        idx = [i for i, w in enumerate(words) if w]
        result: list[dict | None] = [None] * len(words)
        if not idx:
            return result
        tokens, spans = self.tokenize([words[i] for i in idx])
        if not tokens or len(tokens) * 2 > len(emission):
            return result  # nothing alignable, or window too short for this text
        frames_of = token_frames(viterbi(emission, np.array(tokens), self.blank), len(tokens))
        to_s = lambda frame: (frame + frame_offset) / FPS  # noqa: E731
        for i, (a, b) in zip(idx, spans, strict=True):
            frames = [f for j in range(a, b) for f in frames_of[j]]
            if not frames:
                continue
            vowel = next((frames_of[j][0] for j in range(a, b) if tokens[j] in self.vowels), frames[0])
            vowel = min(vowel, frames[0] + int(MAX_VOWEL_DELAY * FPS))
            probs = [np.exp(emission[f, tokens[j]]) for j in range(a, b) for f in frames_of[j]]
            result[i] = {
                "start": max(0.0, to_s(vowel) - ONSET_LAG),
                "onset": max(0.0, to_s(frames[0]) - ONSET_LAG),
                "end": to_s(min(frames[-1] + 1, frames[0] + int(MAX_WORD_S * FPS))),
                "conf": float(np.mean(probs)),
            }
        return result
