"""Gaddy & Klein silent-speech EMG dataset (Zenodo 4064409) as a real-data benchmark.

The dataset is open-vocabulary sentences plus a closed-vocabulary set of dates/times, 8 ch at
1 kHz, single speaker, "silent" = mouthed (lips move). Our use is isolated silent tokens, so we
derive word-classification proxies from the closed-vocabulary utterances: classify the FIRST
word (weekday / month / hour) from a 1 s onset-aligned window, using the exact feature and
segmentation code the live engine uses. Expect lower accuracy than true isolated words: the
window also contains the start of the next word, and there are only ~15-30 examples per class.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np

from . import dsp
from .dataset import Trials

ROOT = Path(__file__).resolve().parents[1] / "data" / "emg_data"
FS = 1000
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def first_word_class(text: str, task: str) -> str | None:
    if not text:
        return None
    w = text.split()[0]
    if task == "weekday":
        return w if w in DAYS else None
    if task == "month":
        return w if w in MONTHS else None
    if task == "hour" and ":" in w:
        return str(int(w.split(":")[0]))
    return None


def utterances(mode: str = "silent"):
    for info in sorted(glob.glob(str(ROOT / "closed_vocab" / mode / "*" / "*_info.json"))):
        meta = json.loads(Path(info).read_text())
        yield info.replace("_info.json", "_emg.npy"), meta.get("text", ""), Path(info).parent.name


def load(task: str = "weekday", mode: str = "silent") -> Trials:
    X, y, g = [], [], []
    for npy, text, day in utterances(mode):
        lab = first_word_class(text, task)
        if lab is None:
            continue
        emg = np.load(npy).astype(np.float64)
        x = dsp.OnlineFilter(FS, emg.shape[1])(emg - emg[:50].mean(0))
        x = x[200:]  # filter settling
        # Utterances are pre-cut, so use a per-utterance relative threshold for the onset:
        # first time the activity score reaches 25% of the way from its floor to its peak.
        ms = dsp.channel_ms(x, FS, tau_s=0.05)[0]
        score = np.mean(ms / (np.percentile(ms, 10, axis=0) + 1e-12), axis=1)
        lo, hi = np.percentile(score, 10), score.max()
        on = int(np.argmax(score > lo + 0.25 * (hi - lo)))
        X.append(dsp.features(dsp.segment(x, FS, on), FS))
        y.append(lab)
        g.append(day)
    groups = np.unique(g, return_inverse=True)[1]
    y = np.array(y)
    return Trials(np.array(X), y, groups, groups, y)


def available() -> bool:
    return (ROOT / "closed_vocab").exists()
