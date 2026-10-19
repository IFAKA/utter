"""Live recognition: stream -> causal filter -> onset detection -> classify -> app token."""
from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np

from . import appbus, dsp, protocol as P
from .stream import Board


class Recognizer:
    def __init__(self, model_path: Path, fs: int, nch: int, p_min: float = 0.6, refractory_s: float = 0.5):
        bundle = joblib.load(model_path)
        self.model, self.meta = bundle["model"], bundle["meta"]
        self.mapping = self.meta.get("mapping") or P.load_tokens()["mapping"]
        self.pairs = [tuple(p) for p in self.meta.get("pairs", [])] or None
        self.fs, self.p_min, self.refr = fs, p_min, int(refractory_s * fs)
        self.filter = dsp.OnlineFilter(fs, nch)
        self.maxn = int(4 * fs)
        self.buf = np.zeros((0, nch))
        self.det: dsp.OnsetDetector | None = None
        self.warm: list[np.ndarray] = []
        self.pending = None  # onset index into self.buf
        self.hold = 0

    def push(self, chunk_uv: np.ndarray) -> list[tuple[str, str, float]]:
        """Feed raw microvolt samples; returns [(label, action, p)] for completed detections."""
        y = self.filter(chunk_uv)
        self.buf = np.vstack([self.buf, y])
        over = len(self.buf) - self.maxn
        if over > 0:
            self.buf = self.buf[over:]
            if self.pending is not None:
                self.pending -= over
        if self.det is None:  # 2 s warm-up: filter settles, then per-channel rest baseline
            self.warm.append(y)
            if sum(len(w) for w in self.warm) >= 2 * self.fs:
                w = np.vstack(self.warm)[int(self.fs):]
                self.det = dsp.OnsetDetector(self.fs, dsp.rest_baseline(w, self.fs))
            return []
        out = []
        on = self.det(y)
        if self.hold > 0:
            self.hold -= len(y)
        elif self.pending is None and on is not None:
            self.pending = len(self.buf) - len(y) + on
        if self.pending is not None and len(self.buf) - self.pending >= int((dsp.SEG_S - dsp.PRE_S) * self.fs):
            seg = dsp.segment(self.buf, self.fs, self.pending)
            proba = self.model.predict_proba(dsp.features(seg, self.fs, self.pairs)[None])[0]
            k = int(np.argmax(proba))
            label, p = str(self.model.classes_[k]), float(proba[k])
            if label != "rest" and p >= self.p_min and label in self.mapping:
                out.append((label, self.mapping[label], p))
            self.pending = None
            self.hold = self.refr
        return out


def run(board: Board, model_path: Path, fs: int = 2000, gain: int = 12, fake: bool = False) -> None:
    rec = Recognizer(model_path, fs, 16)

    def on_chunk(uv, _first):
        for label, action, p in rec.push(uv):
            print(f"{time.strftime('%H:%M:%S')} {label:>6} -> {action:<6} p={p:.2f}", flush=True)
            appbus.token(action, p, "engine")

    board.listeners.append(on_chunk)
    board.start(fs=fs, gain=gain)
    appbus.status("engine streaming")
    print(f"engine: streaming from {board.host}, model {model_path.name}. Ctrl-C to stop.")
    try:
        if fake:  # emulator: you "articulate" by typing a token name; it injects that token's synthetic EMG
            names = sorted(rec.mapping)
            print("fake board: type a token and Enter to articulate it:", " ".join(names))
            while True:
                w = input().strip()
                if w in names:
                    board.cmd(cmd="sim_cue", label=w)
                elif w:
                    print("unknown token; choose from:", " ".join(names))
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, EOFError):
        board.stop()
