"""Live recognition: stream -> causal filter -> onset detection -> classify -> app token."""
from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np

from . import appbus, dsp, protocol as P
from .stream import Board


class Recognizer:
    def __init__(self, model_path: Path, fs: int, nch: int, p_min: float = 0.7, refractory_s: float = 0.5):
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
        self.queued = None  # onset that came during the pause: read once the pause ends, not dropped
        self.hold = 0
        self.notices: list[str] = []  # "unsure" / "too_fast" for the app to voice, drained by the caller

    def push(self, chunk_uv: np.ndarray) -> list[tuple[str, str, float]]:
        """Feed raw microvolt samples; returns [(label, action, p)] for completed detections."""
        y = self.filter(chunk_uv)
        self.buf = np.vstack([self.buf, y])
        over = len(self.buf) - self.maxn
        if over > 0:
            self.buf = self.buf[over:]
            if self.pending is not None:
                self.pending -= over
            if self.queued is not None:
                self.queued -= over
        if self.det is None:  # 2 s warm-up: filter settles, then per-channel rest baseline
            self.warm.append(y)
            if sum(len(w) for w in self.warm) >= 2 * self.fs:
                w = np.vstack(self.warm)[int(self.fs):]
                self.det = dsp.OnsetDetector(self.fs, dsp.rest_baseline(w, self.fs), gap_s=0.15)
            return []
        out = []
        on = self.det(y)
        if on is not None:
            at = len(self.buf) - len(y) + on
            if self.pending is not None:
                self.notices.append("too_fast")  # started inside the previous command's window: it blurs that one
            elif self.hold > 0:
                self.queued = at if self.queued is None else self.queued
            else:
                self.pending = at
        if self.hold > 0:
            self.hold -= len(y)
            if self.hold <= 0 and self.queued is not None:
                self.pending, self.queued = self.queued, None
        if self.pending is not None and len(self.buf) - self.pending >= int((dsp.SEG_S - dsp.PRE_S) * self.fs):
            seg = dsp.segment(self.buf, self.fs, self.pending)
            proba = self.model.predict_proba(dsp.features(seg, self.fs, self.pairs)[None])[0]
            k = int(np.argmax(proba))
            label, p = str(self.model.classes_[k]), float(proba[k])
            if label != "rest" and label in self.mapping:
                if p >= self.p_min:
                    out.append((label, self.mapping[label], p))
                else:
                    self.notices.append("unsure")  # say "again?" rather than drop it silently
            self.pending = None
            self.hold = self.refr
        return out


def run(board: Board, model_path: Path, fs: int = 2000, gain: int = 12, fake: bool = False) -> None:
    rec = Recognizer(model_path, fs, 16)

    def on_chunk(uv, _first):
        for label, action, p in rec.push(uv):
            print(f"{time.strftime('%H:%M:%S')} {label:>6} -> {action:<6} p={p:.2f}", flush=True)
            appbus.token(action, p, "engine")
        for n in rec.notices:
            print(f"{time.strftime('%H:%M:%S')} {n}", flush=True)
            appbus.notice(n)
        rec.notices.clear()

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
