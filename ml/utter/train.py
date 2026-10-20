"""Train, evaluate (within-session, cross-session, cross-day), rank channels, pick tokens."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from . import dsp
from .dataset import Trials

MODELS = Path(__file__).resolve().parents[1] / "data" / "models"


def make_model(kind: str = "lda"):
    if kind == "svm":
        return make_pipeline(StandardScaler(), CalibratedClassifierCV(SVC(C=3.0, gamma="scale"), ensemble=False))
    return make_pipeline(StandardScaler(), LinearDiscriminantAnalysis(solver="lsqr", shrinkage="auto"))


def _acc(model, Xtr, ytr, Xte, yte):
    m = make_model(model).fit(Xtr, ytr)
    p = m.predict(Xte)
    return float(np.mean(p == yte)), p


def within_session(t: Trials, model="lda", folds=5) -> float:
    accs = []
    for g in np.unique(t.group):
        i = t.group == g
        X, y = t.X[i], t.y[i]
        k = min(folds, np.min(np.unique(y, return_counts=True)[1]))
        if k < 2:
            continue
        for tr, te in StratifiedKFold(k, shuffle=True, random_state=0).split(X, y):
            accs.append(_acc(model, X[tr], y[tr], X[te], y[te])[0])
    return float(np.mean(accs)) if accs else float("nan")


def cross_day(t: Trials, model="lda") -> dict:
    """Train on all other days, test on each day."""
    days = np.unique(t.day)
    out = {}
    for d in days:
        tr, te = t.day != d, t.day == d
        if tr.sum() and te.sum():
            out[int(d)] = _acc(model, t.X[tr], t.y[tr], t.X[te], t.y[te])[0]
    return out


def cross_day_calibrated(t: Trials, per_class: int = 3, model="lda", seed: int = 0) -> dict:
    """Like cross_day, but a few trials per class from the test day are added to training
    (the Stage 4 '3-minute calibration'); accuracy is measured on the remaining trials."""
    rng = np.random.default_rng(seed)
    out = {}
    for d in np.unique(t.day):
        te_idx = np.flatnonzero(t.day == d)
        cal = np.concatenate([rng.permutation(te_idx[t.y[te_idx] == c])[:per_class] for c in np.unique(t.y[te_idx])])
        tr = np.concatenate([np.flatnonzero(t.day != d), cal])
        te = np.setdiff1d(te_idx, cal)
        if len(tr) and len(te):
            Xtr = np.vstack([t.X[tr], np.repeat(t.X[cal], 4, 0)])  # upweight the new day
            ytr = np.concatenate([t.y[tr], np.repeat(t.y[cal], 4)])
            out[int(d)] = _acc(model, Xtr, ytr, t.X[te], t.y[te])[0]
    return out


def confusion(t: Trials, model="lda"):
    """Pooled cross-validated confusion matrix (leave-one-session-out when possible)."""
    labels = sorted(np.unique(t.y))
    pred = np.empty_like(t.y)
    groups = np.unique(t.group)
    if len(groups) > 1:
        for g in groups:
            te = t.group == g
            pred[te] = _acc(model, t.X[~te], t.y[~te], t.X[te], t.y[te])[1]
    else:
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=0).split(t.X, t.y):
            pred[te] = _acc(model, t.X[tr], t.y[tr], t.X[te], t.y[te])[1]
    return labels, confusion_matrix(t.y, pred, labels=labels)


# Cost (in extra gestures, roughly) of the decoder receiving action `got` when the user meant `want`:
# a wrong group is undone with one BACK, a false ACCEPT types a wrong word (delete + retype), and so on.
def _confusion_cost(want: str, got: str) -> float:
    if want == got:
        return 0.0
    if want[0] == "G" and got[0] == "G":
        return 1.5
    return {"ACCEPT": 6.0, "NEXT": 2.5, "BACK": 2.0, "WAKE": 3.0}.get(got, 2.0)


# Rough share of each action while typing (groups dominate), from the st-gate token mix.
ACTION_USE = {"G1": .15, "G2": .15, "G3": .15, "G4": .15, "NEXT": .12, "ACCEPT": .18, "BACK": .06, "WAKE": .04}


def assign_actions(labels: list[str], cm: np.ndarray, actions: list[str]) -> dict[str, str]:
    """Token -> action with the lowest expected confusion cost. On SilentWear's real next-day errors the
    alphabetical mapping put the most-confused pair (start/stop) on ACCEPT/BACK; the best mapping lifted
    st-gate from 40-41 to 44/48 sentences."""
    import itertools

    toks = [l for l in labels if l != "rest"]
    P = cm / np.maximum(1, cm.sum(1, keepdims=True))
    ix = {l: i for i, l in enumerate(labels)}
    miss = P[:, ix["rest"]] if "rest" in ix else np.zeros(len(labels))
    C = np.array([[_confusion_cost(a, b) for b in actions] for a in actions])
    use = np.array([ACTION_USE.get(a, 1 / len(actions)) for a in actions])
    best = None
    for perm in itertools.permutations(toks, len(actions)):
        m = [ix[t] for t in perm]
        e = float((use * ((P[np.ix_(m, m)] * C).sum(1) + miss[m])).sum())
        if best is None or e < best[0]:
            best = (e, perm)
    return dict(zip(best[1], actions))


def pick_tokens(t: Trials, n_keep: int = 8, model="lda") -> tuple[list[str], float]:
    """Greedily drop the most-confused candidate until n_keep remain (rest always kept)."""
    keep = [l for l in np.unique(t.y) if l != "rest"]
    while len(keep) > n_keep:
        m = np.isin(t.y, keep + ["rest"])
        sub = Trials(t.X[m], t.y[m], t.group[m], t.day[m], t.raw_label[m])
        labels, cm = confusion(sub, model)
        rec = {l: cm[i, i] / max(1, cm[i].sum()) for i, l in enumerate(labels) if l != "rest"}
        keep.remove(min(rec, key=rec.get))
    m = np.isin(t.y, keep + ["rest"])
    sub = Trials(t.X[m], t.y[m], t.group[m], t.day[m], t.raw_label[m])
    labels, cm = confusion(sub, model)
    return [str(k) for k in keep], float(np.trace(cm) / cm.sum())


def rank_channels(t: Trials, nch: int, model="lda", max_ch: int | None = None,
                  pairs: list[tuple[int, int]] | None = None) -> list[tuple[int, float]]:
    """Greedy forward electrode selection by cross-session (or CV) accuracy; a pair's features count once
    both of its electrodes are chosen."""
    elec = [{int(c[2:]) - 1 for c in dsp.channel_of(n).split("-")} for n in dsp.feature_names(nch, pairs)]
    chosen, out = [], []
    for _ in range(max_ch or nch):
        best = None
        for c in range(nch):
            if c in chosen:
                continue
            cols = np.array([e <= {*chosen, c} for e in elec])
            sub = Trials(t.X[:, cols], t.y, t.group, t.day, t.raw_label)
            labels, cm = confusion(sub, model)
            acc = np.trace(cm) / cm.sum()
            if best is None or acc > best[1]:
                best = (c, float(acc))
        chosen.append(best[0])
        out.append(best)
    return out


def fit_save(t: Trials, name: str, meta: dict, model="lda") -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
    m = make_model(model).fit(t.X, t.y)
    path = MODELS / f"{name}.joblib"
    joblib.dump({"model": m, "meta": meta}, path)
    (MODELS / f"{name}.json").write_text(json.dumps(meta, indent=1))
    return path
