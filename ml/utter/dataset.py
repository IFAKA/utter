"""Recording-session format and trial extraction.

Session dir: emg.npy (n, ch) float32 microvolts, meta.json {fs, nch, gain, day, device, ...},
events.json [{"sample": int, "label": str}] (cue onsets; "rest"/"chew"/"swallow" are rest-class).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import dsp
from .synth import EmgSynth

REST_LABELS = {"rest", "chew", "swallow", "talk"}
SESSIONS = Path(__file__).resolve().parents[1] / "data" / "sessions"


@dataclass
class Trials:
    X: np.ndarray  # (n, feat)
    y: np.ndarray  # labels, rest-class labels collapsed to "rest"
    group: np.ndarray  # session id
    day: np.ndarray
    raw_label: np.ndarray


def save_session(path: Path, emg: np.ndarray, fs: int, events: list[dict], **meta) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    np.save(path / "emg.npy", emg.astype(np.float32))
    (path / "meta.json").write_text(json.dumps({"fs": fs, "nch": emg.shape[1], **meta}, indent=1))
    (path / "events.json").write_text(json.dumps(events))
    return path


def load_session(path: Path):
    meta = json.loads((path / "meta.json").read_text())
    return np.load(path / "emg.npy"), meta, json.loads((path / "events.json").read_text())


def extract(path: Path, pairs=None, search_s: float = 1.2) -> tuple[list[np.ndarray], list[str]]:
    """Onset-aligned features for every cued event in one session."""
    emg, meta, events = load_session(path)
    fs = meta["fs"]
    x = dsp.OnlineFilter(fs, emg.shape[1])(emg.astype(np.float64))  # causal, identical to live engine
    base = dsp.rest_baseline(x[int(fs):], fs)
    feats, labels = [], []
    rng = np.random.default_rng(0)
    for ev in events:
        a = ev["sample"]
        win = x[a:a + int(search_s * fs)]
        if len(win) < int(0.5 * fs):
            continue
        if ev["label"] in REST_LABELS:
            # rest-class: whatever the detector would fire on (chew/swallow), else a random window
            on = dsp.find_onset(win, fs, base)
            on = a + (on if on is not None else int(rng.uniform(0, 0.4) * fs))
        else:
            on = dsp.find_onset(win, fs, base)
            if on is None:  # live engine would not fire either; count as a miss, not a training example
                continue
            on += a
        feats.append(dsp.features(dsp.segment(x, fs, on), fs, pairs))
        labels.append(ev["label"])
    return feats, labels


def load_trials(paths: list[Path], pairs=None) -> Trials:
    X, y, g, d, r = [], [], [], [], []
    for i, p in enumerate(paths):
        meta = json.loads((p / "meta.json").read_text())
        f, lab = extract(p, pairs)
        X += f
        r += lab
        y += ["rest" if l in REST_LABELS else l for l in lab]
        g += [i] * len(f)
        d += [meta.get("day", i)] * len(f)
    return Trials(np.array(X), np.array(y), np.array(g), np.array(d), np.array(r))


def synth_session(path: Path, labels: list[str], reps: int, day: int, session_seed: int,
                  fs: int = 2000, nch: int = 16, seed: int = 0, trial_s: float = 2.0,
                  amp_uv: float = 12.0) -> Path:
    """Write a synthetic session with the same layout the recording game produces."""
    syn = EmgSynth(labels, nch, fs, seed=seed, session_seed=session_seed, amp_uv=amp_uv)
    rng = np.random.default_rng(session_seed)
    order = [l for l in labels for _ in range(reps)] + ["rest", "chew", "swallow"] * max(1, reps // 2)
    rng.shuffle(order)
    n = int(trial_s * fs)
    chunks, events = [], []
    for i, lab in enumerate(order):
        lat = rng.uniform(0.2, 0.45)  # reaction time after cue
        chunks.append(syn.event(lab, n, onset=lat))
        events.append({"sample": i * n, "label": lab})
    return save_session(path, np.vstack(chunks), fs, events, day=day, gain=12, device="synth")
