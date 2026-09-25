import numpy as np

from lyri.ctc import normalize_word, token_frames, viterbi


def test_normalize_word():
    assert normalize_word("Don’t") == "DON'T"
    assert normalize_word("café,") == "CAFE"
    assert normalize_word("2") == "TWO"
    assert normalize_word("&") == "AND"
    assert normalize_word("(oh!)") == "OH"
    assert normalize_word("—") == ""


def _emission(n_frames: int, n_vocab: int, peaks: dict[int, int], blank: int = 0) -> np.ndarray:
    """Log-probs where `blank` dominates except at the given {frame: token} peaks."""
    p = np.full((n_frames, n_vocab), 0.01)
    p[:, blank] = 1.0
    for frame, tok in peaks.items():
        p[frame] = 0.01
        p[frame, tok] = 1.0
    return np.log(p / p.sum(1, keepdims=True))


def test_viterbi_places_tokens_on_their_peaks():
    tokens = np.array([3, 1, 4])
    logp = _emission(40, 6, {5: 3, 18: 1, 30: 4})
    frames = token_frames(viterbi(logp, tokens, blank=0), len(tokens))
    assert [f[0] for f in frames] == [5, 18, 30]


def test_viterbi_handles_repeated_tokens():
    # a repeated token needs a blank in between, CTC-style
    tokens = np.array([2, 2])
    logp = _emission(20, 4, {4: 2, 12: 2})
    frames = token_frames(viterbi(logp, tokens, blank=0), len(tokens))
    assert frames[0][0] == 4 and frames[1][0] == 12


def test_viterbi_path_is_monotonic_and_complete():
    tokens = np.array([1, 2, 3, 1])
    logp = np.log(np.random.default_rng(0).dirichlet(np.ones(5), size=60))
    path = viterbi(logp, tokens, blank=0)
    assert np.all(np.diff(path) >= 0)
    assert set(path[path % 2 == 1] // 2) == {0, 1, 2, 3}  # every token visited
