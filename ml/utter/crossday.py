"""Cross-day recovery for SpeechNet on SilentWear: which cheap fixes close the next-day gap?

Leave-one-day-out per subject. Training variants (flags, combinable):
  --norm  divide each channel by its std over that day (unsupervised: the device can measure it from
          the first minutes of wear, no labels)
  --aug   amplitude, neighbour-channel mixing and time-shift augmentation (electrode drift)
  --pool  pre-train on the other subjects too, then fine-tune on this subject's training days
Each held-out day reports zero-shot accuracy, top-2 accuracy, AdaBN (BatchNorm statistics re-estimated
on the new day's unlabeled windows) and online learning: the day's 5 batches (180 trials ~ 30 typed
words each) arrive in order; after each, fine-tune on everything confirmed so far, test on the next.

Run: uv run --extra lm --with pandas --with tables python -u -m utter.crossday --aug --norm
"""
from __future__ import annotations

import argparse
import copy

import numpy as np

from . import silentwear
from . import speechnet as sn


def normalize(t):
    X = t.X.copy()
    for d in np.unique(t.day):
        m = t.day == d
        X[m] /= X[m].std(axis=(0, 2), keepdims=True) + 1e-6
    t.X[:] = X
    return t


def augment(x):
    import torch

    n, c, _ = x.shape
    gain = torch.exp(0.25 * torch.randn(n, c, 1, device=x.device) + 0.25 * torch.randn(n, 1, 1, device=x.device))
    a = 0.3 * torch.rand(n, 1, 1, device=x.device)
    x = (1 - a) * x + a * torch.roll(x, int(np.random.choice([-1, 1])), 1)
    return torch.roll(x, int(np.random.randint(-50, 51)), 2) * gain


def adabn(net, X):
    import torch

    net = copy.deepcopy(net).to(sn.DEVICE)
    for m in net.modules():
        if isinstance(m, torch.nn.BatchNorm2d):
            m.reset_running_stats()
            m.momentum = None  # cumulative average over all the new day's windows
    net.train()
    with torch.no_grad():
        for b in np.array_split(np.arange(len(X)), max(1, len(X) // 64)):
            net(torch.tensor(X[b], dtype=torch.float32, device=sn.DEVICE))
    return net.eval()


def scores(net, X):
    import torch

    net.eval()
    with torch.no_grad():
        return net(torch.tensor(X, dtype=torch.float32, device=sn.DEVICE)).cpu().numpy()


def softmax(v):
    e = np.exp(v - v.max())
    return [round(float(p), 4) for p in e / e.sum()]


def run(subject, others, args, seed=0, dump=None):
    import torch

    torch.manual_seed(seed)
    np.random.seed(seed)
    t = others[subject]
    classes = np.unique(t.y)
    lab = lambda tt: np.searchsorted(classes, tt.y)
    y = lab(t)
    aug = augment if args.aug else None
    rows = []
    for d in np.unique(t.day):
        tr, te = t.day != d, np.flatnonzero(t.day == d)
        if args.pool:
            Xp = np.concatenate([o.X for s, o in others.items() if s != subject] + [t.X[tr]])
            yp = np.concatenate([lab(o) for s, o in others.items() if s != subject] + [y[tr]])
            base = sn.fit(sn.model(len(classes)), Xp, yp, seed=seed, aug=aug)
            base = sn.fit(base, t.X[tr], y[tr], epochs=30, seed=seed, aug=aug)
        else:
            base = sn.fit(sn.model(len(classes)), t.X[tr], y[tr], seed=seed, aug=aug)
        s = scores(base, t.X[te])
        zs = np.mean(s.argmax(1) == y[te])
        top2 = np.mean((np.argsort(-s, 1)[:, :2] == y[te][:, None]).any(1))
        ab = adabn(base, t.X[te])
        bn = np.mean(scores(ab, t.X[te]).argmax(1) == y[te])
        batches = [te[t.group[te] == g] for g in np.unique(t.group[te])]
        sab = scores(ab, t.X[te])
        online = [np.mean(scores(ab, t.X[batches[0]]).argmax(1) == y[batches[0]])]
        for k in range(1, len(batches)):
            seen = np.concatenate(batches[:k])
            net = sn.fit(copy.deepcopy(ab), t.X[seen], y[seen], epochs=30, val_frac=0, seed=seed, aug=aug, lr=args.ft_lr)
            so = scores(net, t.X[batches[k]])
            online.append(np.mean(so.argmax(1) == y[batches[k]]))
            if dump is not None:
                dump["online"] += [(classes[c], softmax(v)) for c, v in zip(y[batches[k]], so)] if k >= 2 else []
        if dump is not None:
            dump["adabn"] += [(classes[c], softmax(v)) for c, v in zip(y[te], sab)]
        rows.append([zs, top2, bn, *online])
        print(f"  {subject} day {d}: " + " ".join(f"{v * 100:.1f}" for v in rows[-1]), flush=True)
    return np.mean(rows, 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", nargs="*", default=None)
    ap.add_argument("--window", type=float, default=1.4)
    ap.add_argument("--aug", action="store_true")
    ap.add_argument("--norm", action="store_true")
    ap.add_argument("--pool", action="store_true")
    ap.add_argument("--ft-lr", type=float, default=1e-3)
    ap.add_argument("--dump", help="write per-trial softmax outputs (JSON) for st-gate --confusions")
    args = ap.parse_args(argv)
    every = sorted(p.name for p in silentwear.ROOT.iterdir() if (p / "silent").is_dir())
    data = {s: silentwear.load(s, args.window, raw=True) for s in every}
    if args.norm:
        data = {s: normalize(t) for s, t in data.items()}
    print(f"SpeechNet cross-day, window {args.window:.1f} s, aug={args.aug} norm={args.norm} pool={args.pool}")
    print("subject  zero-shot  top-2  AdaBN  online after 0/1/2/3/4 batches")
    rows, dump = [], {"adabn": [], "online": []} if args.dump else None
    for s in args.subjects or every:
        rows.append(run(s, data, args, dump=dump))
        print(f"{s:8s} " + "  ".join(f"{v * 100:5.1f}" for v in rows[-1]), flush=True)
    print(f"{'mean':8s} " + "  ".join(f"{v * 100:5.1f}" for v in np.mean(rows, 0)))
    if args.dump:
        import json

        cls = [str(c) for c in np.unique(next(iter(data.values())).y)]
        sets = {k: [{"label": str(l), "p": p} for l, p in v] for k, v in dump.items()}
        open(args.dump, "w").write(json.dumps({"classes": cls, **sets}))


if __name__ == "__main__":
    main()
