"""Setup wizard: flash, Wi-Fi provisioning, acceptance tests, electrode contact check."""
from __future__ import annotations

import datetime as dt
import getpass
import json
import subprocess
import time
from pathlib import Path

import numpy as np
from rich.console import Console
from rich.live import Live
from rich.table import Table

from . import dsp
from .stream import Board, discover

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "ml" / "data" / "acceptance"
ESP_VID = 0x303A
con = Console()

# Acceptance limits. Datasheet (HR, 2 kSPS, G=12, 3 V): 0.9 uVrms typ; test signal 1 mV, ~0.98 Hz.
NOISE_MAX_UV = 1.5
TEST_PP_MV = (1.8, 2.2)
LOSS_MAX = 0.005


def step(n: int, total: int, text: str):
    con.rule(f"[bold]Step {n}/{total}[/]  {text}")


def find_port(wait_s: float = 120) -> str:
    from serial.tools import list_ports
    t0, said = time.time(), False
    while time.time() - t0 < wait_s:
        for p in list_ports.comports():
            if p.vid == ESP_VID:
                return p.device
        if not said:
            con.print("Plug the board into this Mac with a USB-C cable (battery can stay connected).")
            said = True
        time.sleep(0.5)
    raise SystemExit("No SilentBand on USB found.")


def serial_cmd(port: str, msg: dict, timeout: float = 5.0) -> dict:
    import serial
    with serial.Serial(port, 115200, timeout=0.2) as s:
        s.reset_input_buffer()
        s.write((json.dumps(msg) + "\n").encode())
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = s.readline().decode(errors="ignore").strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass
    raise TimeoutError(f"no serial reply to {msg['cmd']}")


def current_ssid() -> str | None:
    out = subprocess.run(["ipconfig", "getsummary", "en0"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.strip().startswith("SSID :"):
            return line.split(":", 1)[1].strip()
    return None


def flash(port: str) -> None:
    r = subprocess.run(["pio", "run", "-d", str(REPO / "firmware"), "-t", "upload", "--upload-port", port])
    if r.returncode:
        raise SystemExit("Flashing failed; see output above.")


def acceptance(board: Board, fs: int = 2000) -> dict:
    res: dict = {"time": dt.datetime.now().isoformat(timespec="seconds")}
    info = board.cmd(cmd="info")
    res["info"] = info
    res["chip_ids_ok"] = info.get("chip_ids") == [0x92, 0x92]

    board.start(fs=fs, mode="test", leadoff=False)
    board.wait_samples(int(4.5 * fs))
    x = board.last(4.0)
    board.stop()
    pp_mv = (np.percentile(x, 98, 0) - np.percentile(x, 2, 0)) / 1000
    res["test_pp_mV"] = [round(float(v), 3) for v in pp_mv]
    res["test_ok"] = bool(np.all((pp_mv > TEST_PP_MV[0]) & (pp_mv < TEST_PP_MV[1])))

    time.sleep(0.3)
    board.lost, board.last_seq = 0, None
    board.start(fs=fs, mode="shorted", leadoff=False)
    board.wait_samples(int(6 * fs))
    x = board.last(5.0)
    board.stop()
    y = dsp.filt(x - x.mean(0), fs)[fs // 2:-fs // 2]
    noise = np.sqrt(np.mean(y**2, 0))
    res["noise_uVrms"] = [round(float(v), 3) for v in noise]
    res["noise_ok"] = bool(np.all(noise < NOISE_MAX_UV))
    res["packet_loss"] = board.lost / max(1, board.total / 20)
    res["loss_ok"] = res["packet_loss"] < LOSS_MAX
    res["pass"] = all(res[k] for k in ("chip_ids_ok", "test_ok", "noise_ok", "loss_ok"))
    return res


def show(res: dict) -> None:
    t = Table(title="Acceptance test")
    t.add_column("check")
    t.add_column("result")
    t.add_column("")
    ok = lambda b: "[green]PASS[/]" if b else "[red]FAIL[/]"
    t.add_row("ADS1298 IDs (0x92, 0x92)", str(res["info"].get("chip_ids")), ok(res["chip_ids_ok"]))
    t.add_row(f"test signal p-p {TEST_PP_MV} mV", f"{min(res['test_pp_mV'])}..{max(res['test_pp_mV'])}", ok(res["test_ok"]))
    t.add_row(f"shorted noise < {NOISE_MAX_UV} uVrms", f"max {max(res['noise_uVrms'])}", ok(res["noise_ok"]))
    t.add_row(f"packet loss < {LOSS_MAX:.1%}", f"{res['packet_loss']:.3%}", ok(res["loss_ok"]))
    con.print(t)


def setup(skip_flash: bool = False, host: str | None = None) -> None:
    total = 4
    if host is None:
        step(1, total, "connect + flash")
        port = find_port()
        con.print(f"found board on {port}")
        if not skip_flash:
            flash(port)
            time.sleep(3)
            port = find_port()
        info = serial_cmd(port, {"cmd": "info"})
        if info.get("chip_ids") != [0x92, 0x92]:
            con.print(f"[red]ADS1298 not detected[/] (chip ids {info.get('chip_ids')}). Stop here and report.")
            raise SystemExit(1)
        con.print("[green]both ADS1298 chips answer[/]")

        step(2, total, "Wi-Fi")
        ssid = current_ssid() or input("Wi-Fi name: ")
        con.print(f"Using Wi-Fi [bold]{ssid}[/] (same as this Mac).")
        pw = getpass.getpass("Wi-Fi password (sent only to the board over USB): ")
        r = serial_cmd(port, {"cmd": "wifi", "ssid": ssid, "pass": pw}, timeout=20)
        if not r.get("ok"):
            raise SystemExit(f"Wi-Fi failed: {r}")

        step(3, total, "unplug USB")
        con.print("[bold]Unplug the USB cable now.[/] For safety the board only records on battery.")
        while True:
            try:
                find_port(wait_s=0.5)
                time.sleep(0.5)
            except SystemExit:
                break
        con.print("finding board on Wi-Fi...")
        for _ in range(20):
            host = discover()
            if host:
                break
            time.sleep(1)
        if not host:
            raise SystemExit("Board not found on Wi-Fi (mDNS). Is the battery switched on?")
    step(4, total, "acceptance test")
    board = Board(host)
    res = acceptance(board)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{res['time'].replace(':', '')}.json"
    path.write_text(json.dumps(res, indent=1))
    show(res)
    con.print(f"report: {path}")
    con.print("[bold green]Board ready.[/] Next: sb electrodes" if res["pass"] else
              "[bold red]Board failed acceptance.[/] Keep the report; do not record yet.")


def quality(x: np.ndarray, fs: int, lead_p: int, lead_n: int, nch: int = 16) -> list[tuple[str, float, float]]:
    """Per channel: (state, rms_uV 20-450 Hz, hum_uV at 50 Hz)."""
    f = np.fft.rfftfreq(len(x), 1 / fs)
    spec = np.abs(np.fft.rfft((x - x.mean(0)) * np.hanning(len(x))[:, None], axis=0)) * 2 / (len(x) / 2)
    hum = spec[np.abs(f - 50) < 1.5].max(0)
    y = dsp.filt(x - x.mean(0), fs)
    rms = np.sqrt(np.mean(y[fs // 4:] ** 2, 0))
    out = []
    for c in range(nch):
        off = bool((lead_p >> c) & 1 or (lead_n >> c) & 1)
        if off:
            st = "off"
        elif hum[c] > 50 or rms[c] > 30:
            st = "poor"
        else:
            st = "good"
        out.append((st, float(rms[c]), float(hum[c])))
    return out


def electrodes(board: Board, channels: list[int] | None = None, fs: int = 2000) -> None:
    board.start(fs=fs, leadoff=True)
    chans = channels or list(range(16))
    good_since = None
    color = {"good": "green", "poor": "yellow", "off": "red"}
    con.print("Press each electrode firmly for 5 s. Done when all rows are green for 5 s. Ctrl-C to quit.")
    try:
        with Live(console=con, refresh_per_second=4) as live:
            while True:
                time.sleep(0.25)
                x = board.last(1.0)
                if len(x) < fs:
                    continue
                q = quality(x, fs, *board.leadoff)
                t = Table(title="Electrode contact")
                for col in ("ch", "state", "EMG rms uV", "50 Hz uV"):
                    t.add_column(col)
                for c in chans:
                    st, rms, hum = q[c]
                    t.add_row(str(c + 1), f"[{color[st]}]{st}[/]", f"{rms:.1f}", f"{hum:.1f}")
                live.update(t)
                if all(q[c][0] == "good" for c in chans):
                    good_since = good_since or time.time()
                    if time.time() - good_since > 5:
                        break
                else:
                    good_since = None
        con.print("[bold green]All electrodes good.[/] Next: sb record")
    finally:
        board.stop()
