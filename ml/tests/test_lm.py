"""lm.bin round trip: the Swift NeuralPredictor must match a numpy reference of the int8 model."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from utter.lm import ROOT, write_bin

GATE = ROOT / "app/.build/release/st-gate"


def q8(w):
    s = np.maximum(np.abs(w).max(axis=1), 1e-8) / 127
    return np.round(w / s[:, None]) * s[:, None]


def reference(sd, ids, words):
    sig = lambda v: 1 / (1 + np.exp(-v))
    emb, wih, whh, proj = (q8(sd[k]) for k in ["emb.weight", "rnn.weight_ih_l0", "rnn.weight_hh_l0", "proj.weight"])
    b = sd["rnn.bias_ih_l0"] + sd["rnn.bias_hh_l0"]
    H = whh.shape[1]
    h = c = np.zeros(H)
    for t in [1] + [ids.get(w, 2) for w in words]:
        g = wih @ emb[t] + whh @ h + b
        c = sig(g[H : 2 * H]) * c + sig(g[:H]) * np.tanh(g[2 * H : 3 * H])
        h = sig(g[3 * H :]) * np.tanh(c)
    logits = emb @ (proj @ h) + sd["bias"]
    logp = logits - (np.log(np.exp(logits - logits.max()).sum()) + logits.max())
    best = [i for i in np.argsort(-logp) if i >= 3][:5]
    return [(i, logp[i]) for i in best]


@pytest.mark.skipif(not GATE.exists() or not shutil.which("swift"), reason="build app first: swift build -c release")
def test_swift_matches_numpy(tmp_path: Path):
    rng = np.random.default_rng(0)
    V, E, H = 50, 8, 12
    sd = {
        "emb.weight": rng.normal(size=(V, E)),
        "rnn.weight_ih_l0": rng.normal(size=(4 * H, E)),
        "rnn.weight_hh_l0": rng.normal(size=(4 * H, H)),
        "rnn.bias_ih_l0": rng.normal(size=4 * H),
        "rnn.bias_hh_l0": rng.normal(size=4 * H),
        "proj.weight": rng.normal(size=(E, H)),
        "bias": rng.normal(size=V),
    }
    name = lambda i: "w" + "abcdefghijklmnopqrstuvwxyz"[i // 26] + "abcdefghijklmnopqrstuvwxyz"[i % 26]
    vocab = ["<pad>", "<s>", "<unk>"] + [name(i) for i in range(V - 3)]  # letters only, like real words
    write_bin(sd, vocab, tmp_path)
    ids = {w: i for i, w in enumerate(vocab)}
    for ctx in ["", "wab wac", "wab zzz wad"]:
        out = subprocess.run([GATE, "--neural", tmp_path, "--probe", ctx], capture_output=True, text=True, check=True).stdout
        got = [(l.split()[0], float(l.split()[1])) for l in out.splitlines() if l.startswith("w")]
        want = reference(sd, ids, ctx.split())
        assert [w for w, _ in got] == [vocab[i] for i, _ in want], ctx
        assert np.allclose([lp for _, lp in got], [lp for _, lp in want], atol=1e-3), ctx
