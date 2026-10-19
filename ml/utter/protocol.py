"""Utter wire format v1 (see docs/PROTOCOL.md)."""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = 0x4253
VERSION = 1
DATA_PORT = 47700
CTRL_PORT = 47701
APP_PORT = 47800
VREF = 2.4
HEADER = struct.Struct("<HBBIIHBBII")  # 24 bytes
IMU = struct.Struct("<6h")

FLAG_IMU, FLAG_TEST, FLAG_SHORTED, FLAG_VBUS = 1, 2, 4, 8

REPO = Path(__file__).resolve().parents[2]


def load_tokens() -> dict:
    return json.loads((REPO / "config" / "tokens.json").read_text())


def lsb_volts(gain: int = 12) -> float:
    return 2 * VREF / gain / 2**24


@dataclass
class Packet:
    seq: int
    first_sample: int
    fs: int
    flags: int
    leadoff_p: int
    leadoff_n: int
    codes: np.ndarray  # (nframes, nch) int32
    imu: tuple[int, ...] | None = None


def encode(p: Packet) -> bytes:
    nframes, nch = p.codes.shape
    flags = p.flags | (FLAG_IMU if p.imu is not None else 0)
    head = HEADER.pack(MAGIC, VERSION, nch, p.seq & 0xFFFFFFFF, p.first_sample & 0xFFFFFFFF,
                       p.fs, nframes, flags, p.leadoff_p, p.leadoff_n)
    c = p.codes.astype(np.int64).reshape(-1) & 0xFFFFFF
    body = np.stack([(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF], axis=1).astype(np.uint8).tobytes()
    tail = IMU.pack(*p.imu) if p.imu is not None else b""
    return head + body + tail


def decode(buf: bytes) -> Packet:
    if len(buf) < HEADER.size:
        raise ValueError("short packet")
    magic, ver, nch, seq, first, fs, nframes, flags, lp, ln = HEADER.unpack_from(buf)
    if magic != MAGIC or ver != VERSION:
        raise ValueError(f"bad magic/version {magic:#x}/{ver}")
    n = nframes * nch * 3
    raw = np.frombuffer(buf, np.uint8, n, HEADER.size).reshape(-1, 3).astype(np.int32)
    codes = (raw[:, 0] << 16) | (raw[:, 1] << 8) | raw[:, 2]
    codes = np.where(codes & 0x800000, codes - 0x1000000, codes).reshape(nframes, nch)
    imu = None
    if flags & FLAG_IMU:
        imu = IMU.unpack_from(buf, HEADER.size + n)
    return Packet(seq, first, fs, flags, lp, ln, codes, imu)
