"""Guided recording "game": the word is spoken in the earbuds, a tick means "go", and the user
silently articulates it once with lips closed. Short rounds, visible progress, breaks."""
from __future__ import annotations

import datetime as dt
import random
import subprocess
import time

import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn

from . import protocol as P
from .dataset import SESSIONS, save_session
from .stream import Board

REST_PROMPTS = {"rest": "relax", "swallow": "swallow once", "chew": "chew twice"}
TICK = "/System/Library/Sounds/Tink.aiff"
con = Console()


def say(text: str, wait: bool = True):
    p = subprocess.Popen(["say", "-r", "190", text])
    if wait:
        p.wait()


def tick():
    subprocess.Popen(["afplay", TICK])


def plan(labels: list[str], minutes: float, trial_s: float, seed: int) -> list[str]:
    n = int(minutes * 60 / (trial_s + 0.8))  # + spoken prompt
    rest = list(REST_PROMPTS)
    unit = labels + rest * 2  # rest-class trials (relax/swallow/chew) twice per round
    order = []
    rng = random.Random(seed)
    while len(order) < n:
        u = unit[:]
        rng.shuffle(u)
        order += u
    return order[:n]


def run(board: Board, minutes: float = 12.0, labels: list[str] | None = None, fake: bool = False,
        trial_s: float = 2.4, round_len: int = 24, fs: int = 2000, gain: int = 12, seed: int | None = None) -> None:
    labels = labels or P.load_tokens()["candidates"]
    seed = seed if seed is not None else int(time.time())
    order = plan(labels, minutes, trial_s, seed)
    chunks: list[np.ndarray] = []
    board.listeners.append(lambda uv, first: chunks.append(uv))
    board.start(fs=fs, gain=gain)
    board.wait_samples(2 * fs)
    con.print(f"[bold]Recording[/] {len(order)} prompts, ~{minutes:.0f} min, rounds of {round_len}. "
              "Lips closed; after the tick do each one once: a tongue or jaw move, or a syllable shaped [bold]silently[/].")
    say("Recording starts. Keep your lips closed. After the tick, do each one once, silently.")
    events = []
    with Progress(TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
                  console=con) as prog:
        task = prog.add_task("session", total=len(order))
        for i, lab in enumerate(order):
            if i and i % round_len == 0:
                prog.update(task, description=f"[green]round {i // round_len} done, 15 s break")
                say(f"Nice. Round {i // round_len} of {len(order) // round_len} done. Short break.")
                time.sleep(12)
                say("Next round.")
            prompt = REST_PROMPTS.get(lab) or P.load_tokens().get("prompts", {}).get(lab, lab)
            prog.update(task, description=f"[bold cyan]{prompt:^16}")
            say(prompt)
            time.sleep(0.25)
            sample = sum(len(c) for c in chunks)
            tick()
            if fake:
                board.cmd(cmd="sim_cue", label=lab)
            events.append({"sample": sample, "label": lab})
            time.sleep(trial_s)
            prog.advance(task)
    time.sleep(1.0)
    board.stop()
    emg = np.vstack(chunks)
    now = dt.datetime.now()
    path = SESSIONS / now.strftime("%Y%m%d-%H%M%S")
    save_session(path, emg, fs, events, day=now.toordinal(), gain=gain, device="fake" if fake else board.host,
                 lost_packets=board.lost, labels=labels, seed=seed)
    say("Session saved. Thank you.")
    con.print(f"[green]saved[/] {path}  ({len(emg) / fs:.0f} s, {len(events)} prompts, lost packets {board.lost})")
