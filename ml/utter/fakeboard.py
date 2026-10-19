"""Emulates an Utter board over UDP (same protocol as firmware) for hardware-free testing.

Extra emulator-only control command: {"cmd":"sim_cue","label":"ka"} injects that token
~0.35 s later, so the recording game, training and live engine can be tested end to end.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import numpy as np

from . import protocol as P
from .synth import EmgSynth


class FakeBoard:
    def __init__(self, ctrl_port: int = P.CTRL_PORT, seed: int = 0, session_seed: int = 1,
                 leadoff_mask: int = 0, nch: int = 16):
        self.nch = nch
        self.labels = P.load_tokens()["candidates"]
        self.seed, self.session_seed = seed, session_seed
        self.leadoff_mask = leadoff_mask
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", ctrl_port))
        self.dest = None
        self.streaming = False
        self.cfg = {"fs": 2000, "gain": 12, "mode": "normal"}
        self.pending: list[tuple[int, str]] = []
        self.sample = 0
        self.lock = threading.Lock()

    def reply(self, addr, obj):
        self.sock.sendto(json.dumps(obj).encode(), addr)

    def handle(self, msg: dict, addr):
        cmd = msg.get("cmd")
        if cmd == "info":
            self.reply(addr, {"ok": True, "fw": "fake-0.1.0", "chip_ids": [0x92, 0x92], "vbat": 3.92,
                              "vbus": False, "imu": True, "ip": "127.0.0.1", "streaming": self.streaming})
        elif cmd == "subscribe":
            self.dest = (addr[0], int(msg.get("port", P.DATA_PORT)))
            self.reply(addr, {"ok": True})
        elif cmd == "start":
            self.cfg.update({k: msg[k] for k in ("fs", "gain", "mode") if k in msg})
            if self.dest is None:
                self.dest = (addr[0], P.DATA_PORT)
            self.streaming = True
            threading.Thread(target=self.stream, daemon=True).start()
            self.reply(addr, {"ok": True})
        elif cmd == "stop":
            self.streaming = False
            self.reply(addr, {"ok": True})
        elif cmd == "sim_cue":
            with self.lock:
                self.pending.append((self.sample + int(0.35 * self.cfg["fs"]), msg["label"]))
            self.reply(addr, {"ok": True})
        else:
            self.reply(addr, {"ok": False, "err": f"unknown cmd {cmd}"})

    def stream(self):
        fs, gain, mode = int(self.cfg["fs"]), int(self.cfg["gain"]), self.cfg["mode"]
        synth = EmgSynth(self.labels, self.nch, fs, self.seed, self.session_seed)
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        nf, seq, self.sample = 20, 0, 0
        buf = np.zeros((0, self.nch))
        overlay = np.zeros((0, self.nch))  # future additive event signal, aligned with buf's end
        lsb_uv = P.lsb_volts(gain) * 1e6
        t0 = time.monotonic()
        while self.streaming:
            if len(buf) < nf:
                n = fs // 10
                start = self.sample + len(buf)
                if mode == "test":  # internal square wave, (VREFP-VREFN)/2400 = 1 mV, fCLK/2^21 ~ 1 Hz
                    t = (start + np.arange(n)) / fs
                    chunk = np.repeat((np.sign(np.sin(2 * np.pi * 0.98 * t)) * 1000)[:, None], self.nch, 1)
                elif mode == "shorted":
                    chunk = 0.85 * np.random.standard_normal((n, self.nch))
                else:
                    chunk = synth.background(n)
                    with self.lock:
                        due = [p for p in self.pending if p[0] < start + n]
                        self.pending = [p for p in self.pending if p not in due]
                    for at, lab in due:
                        ev = synth.activation(lab, int(1.2 * fs), onset=0.0)
                        k = max(0, at - start)
                        need = k + len(ev)
                        if len(overlay) < need:
                            overlay = np.vstack([overlay, np.zeros((need - len(overlay), self.nch))])
                        overlay[k:need] += ev
                    m = min(n, len(overlay))
                    chunk[:m] += overlay[:m]
                    overlay = overlay[m:]
                buf = np.vstack([buf, chunk])
            frame, buf = buf[:nf], buf[nf:]
            codes = np.clip(np.round(frame / lsb_uv), -2**23, 2**23 - 1).astype(np.int32)
            flags = {"test": P.FLAG_TEST, "shorted": P.FLAG_SHORTED}.get(mode, 0)
            pkt = P.Packet(seq, self.sample, fs, flags, self.leadoff_mask, self.leadoff_mask, codes,
                           imu=(0, 0, 16384, 0, 0, 0))
            out.sendto(P.encode(pkt), self.dest)
            seq += 1
            self.sample += nf
            delay = t0 + self.sample / fs - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def serve(self):
        while True:
            data, addr = self.sock.recvfrom(4096)
            try:
                self.handle(json.loads(data), addr)
            except Exception as e:  # keep the emulator alive on bad input
                self.reply(addr, {"ok": False, "err": str(e)})
