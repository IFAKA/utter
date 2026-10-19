"""Keyboard-as-fake-sensor: keys stand in for silent tokens, with injected recognition errors."""
from __future__ import annotations

import random
import sys
import termios
import tty

from . import appbus

KEYS = {"a": "G1", "s": "G2", "d": "G3", "f": "G4", "j": "NEXT", "k": "ACCEPT", "l": "BACK", " ": "WAKE"}
ACTIONS = list(dict.fromkeys(KEYS.values()))


def corrupt(action: str, acc: float, rng: random.Random) -> str | None:
    """Return the recognized action: correct with prob acc, else a miss (25%) or a confusion."""
    if rng.random() < acc:
        return action
    if rng.random() < 0.25:
        return None
    return rng.choice([a for a in ACTIONS if a != action])


def run(acc: float = 0.8, seed: int | None = None) -> None:
    rng = random.Random(seed)
    print(f"keysim: accuracy {acc:.0%}.  a s d f = letter groups  j NEXT  k ACCEPT  l BACK  space WAKE  q quit")
    appbus.status(f"keysim connected ({acc:.0%})")
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "q":
                break
            if ch not in KEYS:
                continue
            out = corrupt(KEYS[ch], acc, rng)
            mark = "ok " if out == KEYS[ch] else "ERR"
            print(f"\r{mark} {KEYS[ch]:>6} -> {out or '(missed)':<8}", flush=True)
            if out:
                appbus.token(out, 1.0, "keysim")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
