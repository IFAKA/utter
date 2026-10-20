"""SpeechNet: the small CNN from SilentWear (pulp-bio/SilentWear, Apache-2.0), on raw filtered windows.

Same blocks and training config as their paper config (config/models_configs/speechnet_config.yaml):
temporal convs (1x4 pool 8, 1x16 pool 4, 1x8 pool 4) then two spatial convs (7x1), global average pool,
dropout 0.5, linear. Adam 1e-3, weight decay 1e-4, ReduceLROnPlateau(0.1, 2), early stop 10, max 100 epochs.
Fine-tuning (their IV_inter_session_with_ft): the whole net, lr 1e-3, 50 epochs, on the new day's trials.

Run: uv run --extra lm --with pandas --with tables python -m utter.speechnet --subjects S01
"""
from __future__ import annotations

import argparse
import copy

import numpy as np

from . import silentwear

DEVICE = "mps"  # torch's CPU conv path is ~12x slower for these 1xk kernels
BLOCKS = [(8, (1, 4), (1, 8)), (16, (1, 16), (1, 4)), (16, (1, 8), (1, 4)), (32, (7, 1), (1, 1)), (32, (7, 1), (1, 1))]


def model(n_classes: int):
    import torch.nn as nn

    layers, c = [], 1
    for out, (kc, kt), pool in BLOCKS:
        layers += [nn.Conv2d(c, out, (kc, kt), padding=(0, kt // 2)), nn.BatchNorm2d(out), nn.ReLU(), nn.MaxPool2d(pool)]
        c = out
    return nn.Sequential(nn.Unflatten(1, (1, -1)), *layers, nn.AdaptiveAvgPool2d(1), nn.Flatten(),
                         nn.Dropout(0.5), nn.Linear(c, n_classes))


def fit(net, X, y, epochs=100, patience=10, seed=0, val_frac=0.15, lr=1e-3, aug=None):
    """Train with a held-out slice of the training data for LR scheduling and early stopping;
    val_frac=0 trains for exactly `epochs` (fine-tuning on a handful of trials). `aug` maps a batch to a
    perturbed copy (training only)."""
    import torch

    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    nv = int(len(y) * val_frac)
    va, tr = idx[:nv], idx[nv:]
    net.to(DEVICE)
    Xt, yt = torch.tensor(X, dtype=torch.float32, device=DEVICE), torch.tensor(y, device=DEVICE)
    va = torch.as_tensor(va, device=DEVICE)
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.1, patience=2)
    lossf = torch.nn.CrossEntropyLoss()
    best, best_state, wait = np.inf, copy.deepcopy(net.state_dict()), 0
    g = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        net.train()
        for b in torch.randperm(len(tr), generator=g).split(32):
            i = torch.as_tensor(tr[b.numpy()], device=DEVICE)
            if len(i) < 2:
                continue
            opt.zero_grad()
            xb = Xt[i] if aug is None else aug(Xt[i])
            lossf(net(xb), yt[i]).backward()
            opt.step()
        if not nv:
            continue
        net.eval()
        with torch.no_grad():
            v = lossf(net(Xt[va]), yt[va]).item()
        sched.step(v)
        if v < best:
            best, best_state, wait = v, copy.deepcopy(net.state_dict()), 0
        elif (wait := wait + 1) >= patience:
            break
    if nv:
        net.load_state_dict(best_state)
    return net


def predict(net, X):
    import torch

    net.eval()
    with torch.no_grad():
        return net(torch.tensor(X, dtype=torch.float32, device=DEVICE)).argmax(1).cpu().numpy()


def evaluate(t, seed=0):
    import torch

    torch.manual_seed(seed)
    classes, y = np.unique(t.y, return_inverse=True)
    acc = lambda net, te: float(np.mean(predict(net, t.X[te]) == y[te]))
    within = []
    for d in np.unique(t.day):
        for g in np.unique(t.group[t.day == d]):
            tr, te = (t.day == d) & (t.group != g), t.group == g
            within.append(acc(fit(model(len(classes)), t.X[tr], y[tr], seed=seed), te))
            print(f"  within day {d} batch {g}: {within[-1] * 100:.1f}%", flush=True)
    cross, cal = [], {3: [], 14: []}
    for d in np.unique(t.day):
        tr, te = t.day != d, t.day == d
        base = fit(model(len(classes)), t.X[tr], y[tr], seed=seed)
        cross.append(acc(base, te))
        print(f"  cross day {d}: {cross[-1] * 100:.1f}%", flush=True)
        for k in cal:
            # Same calibration trials as train.cross_day_calibrated (same rng and order), so LDA vs CNN is paired.
            rng = np.random.default_rng(0)
            te_idx = np.flatnonzero(te)
            for dd in np.unique(t.day):
                ti = np.flatnonzero(t.day == dd)
                c = np.concatenate([rng.permutation(ti[t.y[ti] == cl])[:k] for cl in np.unique(t.y[ti])])
                if dd == d:
                    break
            net = fit(copy.deepcopy(base), t.X[c], y[c], epochs=50, val_frac=0, seed=seed)
            cal[k].append(acc(net, np.setdiff1d(te_idx, c)))
    return [np.mean(within), np.mean(cross), np.mean(cal[3]), np.mean(cal[14])]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", nargs="*", default=None)
    ap.add_argument("--window", type=float, default=1.4)
    args = ap.parse_args(argv)
    subjects = args.subjects or sorted(p.name for p in silentwear.ROOT.iterdir() if (p / "silent").is_dir())
    print(f"SpeechNet, window {args.window:.1f} s, 9 classes")
    print("subject  within-session  cross-day  +3/class ft  +14/class ft")
    rows = []
    for s in subjects:
        r = evaluate(silentwear.load(s, args.window, raw=True))
        rows.append(r)
        print(f"{s:8s} " + "  ".join(f"{v * 100:11.1f}%" for v in r), flush=True)
    a = np.array(rows)
    print(f"{'mean':8s} " + "  ".join(f"{v * 100:6.1f}±{e * 100:4.1f}%" for v, e in zip(a.mean(0), a.std(0))))


if __name__ == "__main__":
    main()
