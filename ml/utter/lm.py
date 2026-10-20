"""Tiny next-word LSTM for on-device decoding (Gboard-class: ~1.4M params, ~1.4 MB int8).

Train:  uv run --extra lm python -m utter.lm train data/lm-src/*.parquet --out data/lm
Output: data/lm/vocab.txt (one word per line, id = line) and data/lm/lm.bin (int8, see export()).
Data:   SODA dialogues (allenai/soda, CC-BY-4.0), split into sentences. Sentences that appear in the
        st-gate benchmark are dropped so the benchmark stays held out.
"""
import argparse
import re
import struct
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORD = re.compile(r"[a-z']+")
SPLIT = re.compile(r"[.?!\n]+")
PAD, BOS, UNK = 0, 1, 2  # BOS doubles as end of sentence


def sentences(paths):
    import pyarrow.parquet as pq

    for p in paths:
        for dialog in pq.read_table(p, columns=["dialogue"]).column("dialogue").to_pylist():
            for turn in dialog:
                for s in SPLIT.split(turn.lower()):
                    w = WORD.findall(s)
                    if w:
                        yield w


def held_out():
    """Benchmark sentences in app/Sources/st-gate/main.swift, normalised like the training text."""
    src = (ROOT / "app/Sources/st-gate/main.swift").read_text()
    return {" ".join(WORD.findall(s.lower())) for s in re.findall(r'"([^"\\]{8,})"', src)}


def lexicon():
    words = set()
    for line in (ROOT / "app/Sources/TypingCore/Resources/words_en.txt").read_text().splitlines():
        if line:
            words.add(line.split("\t")[0].lower())
    return words


def build(paths, vocab_size, max_sents):
    skip, lex = held_out(), lexicon()
    sents, dropped = [], 0
    for w in sentences(paths):
        if " ".join(w) in skip:
            dropped += 1
            continue
        sents.append(w)
        if len(sents) >= max_sents:
            break
    counts = Counter(x for s in sents for x in s if x in lex)
    vocab = ["<pad>", "<s>", "<unk>"] + [w for w, _ in counts.most_common(vocab_size - 3)]
    print(f"{len(sents)} sentences, {sum(map(len, sents))} words, dropped {dropped} benchmark sentences, vocab {len(vocab)}")
    return sents, vocab


def model(V, E, H):
    import torch
    import torch.nn as nn

    class LM(nn.Module):
        """Embedding tied with the output layer; a projection maps the LSTM state back to E."""

        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(V, E, padding_idx=PAD)
            self.rnn = nn.LSTM(E, H, batch_first=True)
            self.proj = nn.Linear(H, E, bias=False)
            self.bias = nn.Parameter(torch.zeros(V))

        def forward(self, x):
            h, _ = self.rnn(self.emb(x))
            return self.proj(h) @ self.emb.weight.T + self.bias

    return LM()


def train(args):
    import random
    import torch
    import torch.nn.functional as F

    sents, vocab = build(args.data, args.vocab, args.max_sents)
    ids = {w: i for i, w in enumerate(vocab)}
    data = [[BOS] + [ids.get(w, UNK) for w in s[: args.max_len]] + [BOS] for s in sents]
    random.Random(0).shuffle(data)
    n_val = min(5000, len(data) // 20)
    val, data = data[:n_val], data[n_val:]
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    m = model(len(vocab), args.emb, args.hidden).to(dev)
    print(f"{sum(p.numel() for p in m.parameters()) / 1e6:.2f}M params on {dev}")
    opt = torch.optim.Adam(m.parameters(), lr=args.lr)

    def batches(rows, shuffle):
        rows = sorted(rows, key=len)  # similar lengths per batch: little padding
        chunks = [rows[i : i + args.batch] for i in range(0, len(rows), args.batch)]
        if shuffle:
            random.shuffle(chunks)
        for c in chunks:
            L = max(map(len, c))
            yield torch.tensor([r + [PAD] * (L - len(r)) for r in c], device=dev)

    def loss_of(x):
        logits = m(x[:, :-1])
        return F.cross_entropy(logits.reshape(-1, logits.size(-1)), x[:, 1:].reshape(-1), ignore_index=PAD)

    for ep in range(args.epochs):
        m.train()
        for i, x in enumerate(batches(data, True)):
            opt.zero_grad()
            loss = loss_of(x)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            if i % 500 == 0:
                print(f"epoch {ep} step {i} loss {loss.item():.3f}", flush=True)
        m.eval()
        with torch.no_grad():
            v = [loss_of(x).item() for x in batches(val, False)]
        print(f"epoch {ep} val loss {sum(v) / len(v):.3f} (ppl {2.718281828 ** (sum(v) / len(v)):.0f})", flush=True)
    export(m, vocab, Path(args.out))


def export(m, vocab, out):
    """lm.bin: magic "ULM1", V E H (int32), then tensors as [rows int32, cols int32, scales f32[rows], int8[rows*cols]]:
    emb (V x E), w_ih (4H x E), w_hh (4H x H), b (4H, f32: b_ih + b_hh), proj (E x H), bias (V, f32).
    Gate order i, f, g, o (PyTorch). Per-row symmetric int8."""
    write_bin({k: v.detach().float().cpu().numpy() for k, v in m.state_dict().items()}, vocab, out)


def write_bin(sd, vocab, out):
    import numpy as np

    out.mkdir(parents=True, exist_ok=True)
    (out / "vocab.txt").write_text("\n".join(vocab) + "\n")
    V, E = sd["emb.weight"].shape
    H = sd["rnn.weight_hh_l0"].shape[1]
    with open(out / "lm.bin", "wb") as f:
        f.write(b"ULM1" + struct.pack("<3i", V, E, H))

        def q8(w):
            s = np.maximum(np.abs(w).max(axis=1), 1e-8) / 127
            f.write(struct.pack("<2i", *w.shape))
            f.write(s.astype("<f4").tobytes())
            f.write(np.round(w / s[:, None]).astype(np.int8).tobytes())

        def f32(v):
            f.write(struct.pack("<i", v.size) + v.astype("<f4").tobytes())

        q8(sd["emb.weight"])
        q8(sd["rnn.weight_ih_l0"])
        q8(sd["rnn.weight_hh_l0"])
        f32(sd["rnn.bias_ih_l0"] + sd["rnn.bias_hh_l0"])
        q8(sd["proj.weight"])
        f32(sd["bias"])
    print(f"wrote {out / 'lm.bin'} ({(out / 'lm.bin').stat().st_size / 1e6:.2f} MB), {len(vocab)} words")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("data", nargs="+")
    t.add_argument("--out", default=str(ROOT / "ml/data/lm"))
    t.add_argument("--vocab", type=int, default=10000)
    t.add_argument("--emb", type=int, default=96)
    t.add_argument("--hidden", type=int, default=256)
    t.add_argument("--epochs", type=int, default=3)
    t.add_argument("--batch", type=int, default=256)
    t.add_argument("--lr", type=float, default=2e-3)
    t.add_argument("--max-len", type=int, default=30)
    t.add_argument("--max-sents", type=int, default=2_000_000)
    args = ap.parse_args()
    train(args)


if __name__ == "__main__":
    main()
