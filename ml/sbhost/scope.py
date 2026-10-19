"""Live 16-channel view (filtered 20-450 Hz). With --fake, the emulator articulates a random
token every 2.5 s so the bursts and their spatial patterns are visible."""
from __future__ import annotations

import random
import time

import numpy as np

from . import dsp
from . import protocol as P

WINDOW_S = 5.0
CUE_S = 2.5


def run(board, fake: bool = False):
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    r = board.start(fs=2000, gain=12)
    if not r.get("ok", True):
        raise SystemExit(f"start refused: {r.get('err')}")
    fs = board.fs
    labels = P.load_tokens()["candidates"]
    n = int(WINDOW_S * fs)
    t = np.arange(n) / fs - WINDOW_S
    fig, ax = plt.subplots(figsize=(11, 8))
    fig.canvas.manager.set_window_title("SilentBand scope")
    lines = [ax.plot(t, np.zeros(n), lw=0.6)[0] for _ in range(16)]
    ax.set_xlim(-WINDOW_S, 0); ax.set_ylim(-1, 16.5)
    ax.set_yticks(range(16), [f"ch{c + 1}" for c in range(16)])
    ax.set_xlabel("s"); ax.invert_yaxis()
    status = ax.set_title("")
    cue = {"at": 0.0, "label": ""}

    def update(_):
        if fake and time.time() - cue["at"] > CUE_S:
            cue["label"] = random.choice(labels)
            cue["at"] = time.time()
            board.cmd(cmd="sim_cue", label=cue["label"])
        x = board.last(WINDOW_S + 0.5)
        if len(x) < fs:
            return lines
        y = dsp.filt(x, fs)[-n:]
        scale = max(np.percentile(np.abs(y), 99), 1.0)  # uV per lane
        for c, ln in enumerate(lines):
            ln.set_data(t[-len(y):], c + y[:, c] / (2.2 * scale))
        lo = "".join("x" if (board.leadoff[0] >> c) & 1 else "." for c in range(16)) if board.leadoff[0] else "all ok"
        what = f"   token: {cue['label']}" if fake else ""
        status.set_text(f"{scale:.0f} uV/lane   lead-off: {lo}{what}")
        return lines

    _anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)
    try:
        plt.show()
    finally:
        board.stop()
