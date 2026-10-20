"""SilentWear (PulpBio/SilentWear on Hugging Face, Apache-2.0) as a real-data check of our token classifier.

14-ch textile neck EMG at 500 Hz, 4 subjects x 3 days, 5 silent batches per day, 20 reps of 8 commands
(up down left right start stop forward backward) + rest per batch. Same splits as the paper
(arXiv 2603.02847): within-session leave-one-batch-out, and cross-session leave-one-day-out, plus our
short calibration (a few trials per class from the new day). Features and classifiers are the ones the
live engine uses (dsp.features + LDA/SVM), so the numbers say what our pipeline would get on this signal.

Download: hf download PulpBio/SilentWear --repo-type dataset --include "data_raw_and_filt/S0*/silent/*.h5" \
              --local-dir data/silentwear
Run:      uv run --with pandas --with tables python -m utter.silentwear
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from . import dsp, train
from .dataset import Trials

ROOT = Path(__file__).resolve().parents[1] / "data" / "silentwear" / "data_raw_and_filt"
FS = 500
REST_PER_BATCH = 20  # match the 20 reps per word


def load(subject: str, window_s: float = 1.4, condition: str = "silent", raw: bool = False) -> Trials:
    """raw=True keeps the filtered window itself (N x channels x samples) for the CNN instead of features."""
    import pandas as pd

    X, y, group, day = [], [], [], []
    n = int(window_s * FS)
    for f in sorted((ROOT / subject / condition).glob("sess_*_batch_*.h5")):
        d = pd.read_hdf(f, "emg")
        emg = d[[c for c in d.columns if c.endswith("_filt")]].to_numpy(np.float64)
        lab = d["Label_str"].to_numpy()
        sess, batch = int(d["session_id"].iloc[0]), int(d["batch_id"].iloc[0])
        cut = np.flatnonzero(lab[1:] != lab[:-1]) + 1
        runs = [(s, e) for s, e in zip(np.r_[0, cut], np.r_[cut, len(lab)]) if e - s >= n]
        rest = [r for r in runs if lab[r[0]] == "rest"]
        keep = {rest[i] for i in np.linspace(0, len(rest) - 1, min(REST_PER_BATCH, len(rest))).astype(int)}
        for s, e in runs:
            if lab[s] == "rest" and (s, e) not in keep:
                continue
            X.append(emg[s : s + n].T.astype(np.float32) if raw else dsp.features(emg[s : s + n], FS))
            y.append(lab[s])
            group.append(sess * 10 + batch)
            day.append(sess)
    y = np.array(y)
    return Trials(np.array(X), y, np.array(group), np.array(day), y)


def leave_one_batch_out(t: Trials, model: str) -> float:
    """Paper's within-session protocol: per day, train on 4 batches, test on the 5th."""
    accs = []
    for d in np.unique(t.day):
        for g in np.unique(t.group[t.day == d]):
            tr, te = (t.day == d) & (t.group != g), t.group == g
            accs.append(train._acc(model, t.X[tr], t.y[tr], t.X[te], t.y[te])[0])
    return float(np.mean(accs))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", nargs="*", default=None)
    ap.add_argument("--window", type=float, default=1.4)
    ap.add_argument("--models", nargs="*", default=["lda", "svm"])
    args = ap.parse_args(argv)
    subjects = args.subjects or sorted(p.name for p in ROOT.iterdir() if (p / "silent").is_dir())
    print(f"window {args.window:.1f} s, 9 classes (8 words + rest), chance 11%")
    print("subject model  within-session  cross-day  +3/class cal  +14/class cal")
    rows = {m: [] for m in args.models}
    for s in subjects:
        t = load(s, args.window)
        for m in args.models:
            r = [leave_one_batch_out(t, m), np.mean(list(train.cross_day(t, m).values())),
                 np.mean(list(train.cross_day_calibrated(t, 3, m).values())),
                 np.mean(list(train.cross_day_calibrated(t, 14, m).values()))]
            rows[m].append(r)
            print(f"{s:7s} {m:5s} " + "  ".join(f"{v * 100:12.1f}%" for v in r), flush=True)
    for m, r in rows.items():
        a = np.array(r)
        print(f"{'mean':7s} {m:5s} " + "  ".join(f"{v * 100:7.1f}±{e * 100:4.1f}%" for v, e in zip(a.mean(0), a.std(0))))


if __name__ == "__main__":
    main()
