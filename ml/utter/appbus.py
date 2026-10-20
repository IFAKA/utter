"""Token events to the Mac app (UDP JSON on localhost)."""
from __future__ import annotations

import json
import socket

from . import protocol as P

_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send(obj: dict, port: int = P.APP_PORT) -> None:
    _sock.sendto(json.dumps(obj).encode(), ("127.0.0.1", port))


def token(action: str, p: float = 1.0, src: str = "engine") -> None:
    send({"type": "token", "action": action, "p": round(float(p), 3), "src": src})


def notice(what: str) -> None:
    """A command the engine couldn't use: "unsure" (below p_min) or "too_fast" (overlapped the last)."""
    send({"type": "notice", "what": what})


def status(text: str) -> None:
    send({"type": "status", "text": text})
