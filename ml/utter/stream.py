"""Board discovery, control and streaming receiver."""
from __future__ import annotations

import json
import socket
import threading
import time
from collections import deque

import numpy as np

from . import protocol as P


def discover(timeout: float = 3.0) -> str | None:
    """Resolve utter.local via mDNS; returns IP or None."""
    try:
        from zeroconf import Zeroconf
        zc = Zeroconf()
        try:
            info = zc.get_service_info("_utter._udp.local.", "utter._utter._udp.local.",
                                       timeout=int(timeout * 1000))
            if info and info.parsed_addresses():
                return info.parsed_addresses()[0]
        finally:
            zc.close()
    except Exception:
        pass
    try:
        return socket.gethostbyname("utter.local")
    except OSError:
        return None


class Board:
    """Control client + data receiver. Samples are converted to microvolts."""

    def __init__(self, host: str, data_port: int = P.DATA_PORT, keep_s: float = 30.0, ctrl_port: int = P.CTRL_PORT):
        self.host, self.ctrl_port = host, ctrl_port
        self.ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl.settimeout(1.5)
        self.data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self.data.bind(("0.0.0.0", data_port))
        self.data.settimeout(0.5)
        self.data_port = data_port
        self.gain, self.fs = 12, 2000
        self.chunks: deque = deque()
        self.keep_s = keep_s
        self.lock = threading.Lock()
        self.total = 0  # samples received
        self.lost = 0
        self.last_seq = None
        self.leadoff = (0, 0)
        self.flags = 0
        self.imu = None
        self.listeners: list = []  # callables(chunk_uv, first_sample)
        self._run = False

    def cmd(self, **msg) -> dict:
        data = json.dumps(msg).encode()
        for _ in range(3):
            self.ctrl.sendto(data, (self.host, self.ctrl_port))
            try:
                return json.loads(self.ctrl.recvfrom(4096)[0])
            except socket.timeout:
                continue
        raise TimeoutError(f"board {self.host} did not answer {msg.get('cmd')}")

    def start(self, fs: int = 2000, gain: int = 12, mode: str = "normal", leadoff: bool = True) -> dict:
        self.fs, self.gain = fs, gain
        self.cmd(cmd="subscribe", port=self.data_port)
        self._run = True
        threading.Thread(target=self._rx, daemon=True).start()
        r = self.cmd(cmd="start", fs=fs, gain=gain, mode=mode, leadoff=leadoff)
        if not r.get("ok"):
            self._run = False
            raise RuntimeError(f"start refused: {r.get('err')}")
        return r

    def stop(self):
        try:
            self.cmd(cmd="stop")
        finally:
            self._run = False

    def _rx(self):
        lsb_uv = P.lsb_volts(self.gain) * 1e6
        while self._run:
            try:
                buf = self.data.recvfrom(65536)[0]
                pkt = P.decode(buf)
            except (socket.timeout, ValueError):
                continue
            if self.last_seq is not None and pkt.seq != self.last_seq + 1:
                self.lost += max(0, pkt.seq - self.last_seq - 1)
            self.last_seq = pkt.seq
            uv = pkt.codes * lsb_uv
            with self.lock:
                self.chunks.append(uv)
                self.total += len(uv)
                while sum(len(c) for c in self.chunks) > self.keep_s * pkt.fs:
                    self.chunks.popleft()
                self.leadoff, self.flags, self.imu = (pkt.leadoff_p, pkt.leadoff_n), pkt.flags, pkt.imu
            for f in self.listeners:
                f(uv, pkt.first_sample)

    def last(self, seconds: float) -> np.ndarray:
        with self.lock:
            x = np.vstack(list(self.chunks)) if self.chunks else np.zeros((0, 16))
        return x[-int(seconds * self.fs):]

    def wait_samples(self, n: int, timeout: float = 10.0) -> bool:
        t0, start = time.time(), self.total
        while self.total - start < n:
            if time.time() - t0 > timeout:
                return False
            time.sleep(0.02)
        return True
