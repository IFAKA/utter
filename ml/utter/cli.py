"""`utter` command line: one entry point for every host-side step."""
from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from pathlib import Path

import numpy as np

from . import protocol as P


def _board(args):
    from .stream import Board, discover
    if getattr(args, "fake", False):
        from .fakeboard import FakeBoard
        fb = FakeBoard(ctrl_port=P.CTRL_PORT, session_seed=int(time.time()) % 1000)
        threading.Thread(target=fb.serve, daemon=True).start()
        return Board("127.0.0.1")
    host = args.host or discover()
    if not host:
        raise SystemExit("Board not found (mDNS). Pass --host IP or use --fake.")
    return Board(host)


def cmd_fakeboard(args):
    from .fakeboard import FakeBoard
    print(f"fake Utter on udp/{P.CTRL_PORT} (Ctrl-C to stop)")
    FakeBoard(leadoff_mask=args.leadoff_mask).serve()


def cmd_setup(args):
    from . import wizard
    wizard.setup(skip_flash=args.no_flash, host=args.host)


def cmd_test(args):
    from . import wizard
    res = wizard.acceptance(_board(args))
    wizard.show(res)
    raise SystemExit(0 if res["pass"] else 1)


def cmd_electrodes(args):
    from . import wizard
    wizard.electrodes(_board(args))


def cmd_scope(args):
    from . import scope
    scope.run(_board(args), fake=args.fake)


def cmd_record(args):
    from . import record
    record.run(_board(args), minutes=args.minutes, fake=args.fake)


def _sessions(paths):
    from .dataset import SESSIONS
    ps = [Path(p) for p in paths] if paths else sorted(p for p in SESSIONS.glob("*") if (p / "emg.npy").exists())
    if not ps:
        raise SystemExit("No sessions. Record with `utter record` (or `utter synth` for synthetic ones).")
    return ps


def cmd_synth(args):
    from .dataset import SESSIONS, synth_session
    tok = P.load_tokens()["candidates"]
    for i in range(args.sessions):
        p = synth_session(SESSIONS / f"synth-{i}", tok, reps=args.reps, day=i // 2, session_seed=100 + i)
        print("wrote", p)


def cmd_train(args):
    from . import dataset, neckband, train
    paths = _sessions(args.sessions)
    pairs = neckband.PAIRS if all(json.loads((p / "meta.json").read_text())["nch"] == 16 for p in paths) else None
    t = dataset.load_trials(paths, pairs)
    tok = P.load_tokens()
    rep: dict = {"sessions": [str(p) for p in paths], "n_trials": int(len(t.y)),
                 "per_class": {str(k): int(v) for k, v in zip(*np.unique(t.y, return_counts=True))}}
    rep["within_session"] = train.within_session(t, args.model)
    if len(np.unique(t.day)) > 1:
        rep["cross_day"] = train.cross_day(t, args.model)
        rep["cross_day_calibrated_3"] = train.cross_day_calibrated(t, 3, args.model)
    keep, acc = train.pick_tokens(t, 8, args.model)
    rep["kept_tokens"], rep["kept_accuracy"] = keep, acc
    m = np.isin(t.y, keep + ["rest"])
    sub = dataset.Trials(t.X[m], t.y[m], t.group[m], t.day[m], t.raw_label[m])
    labels, cm = train.confusion(sub, args.model)
    mapping = train.assign_actions(labels, cm, tok["actions"])
    rep["mapping"] = mapping
    rep["confusion"] = {"labels": labels, "matrix": cm.tolist()}
    if args.rank:
        rep["channel_rank"] = train.rank_channels(sub, 16, args.model, max_ch=args.rank, pairs=pairs)
    path = train.fit_save(sub, args.name, {"mapping": mapping, "model": args.model, "fs": 2000, "pairs": pairs or []}, args.model)
    print(json.dumps({k: v for k, v in rep.items() if k != "confusion"}, indent=1, default=float))
    gate = "PASS" if acc > 0.8 else "FAIL"
    print(f"\nStage 2 gate (>80% on kept tokens incl. rest): {acc:.1%} -> {gate}\nmodel: {path}")
    (path.with_suffix(".report.json")).write_text(json.dumps(rep, indent=1, default=float))


def cmd_engine(args):
    from . import engine
    from .train import MODELS
    engine.run(_board(args), MODELS / f"{args.name}.joblib", fake=args.fake)


def cmd_keysim(args):
    from . import keysim
    keysim.run(args.accuracy)


def cmd_gaddy(args):
    from . import gaddy, train
    if not gaddy.available():
        raise SystemExit("Gaddy data missing: see ml/README.md (download + extract to ml/data/emg_data).")
    for task in ("weekday", "month", "hour"):
        for mode in ("silent", "voiced"):
            t = gaddy.load(task, mode)
            counts = np.unique(t.y, return_counts=True)[1]
            acc = train.within_session(t, "lda")
            print(f"{task:8} {mode:7} n={len(t.y):4} classes={len(counts):2} chance={counts.max() / len(t.y):.2f}"
                  f"  5-fold LDA={acc:.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="utter", description="Utter host tools")
    sub = ap.add_subparsers(required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        p.add_argument("--host", help="board IP (default: mDNS utter.local)")
        p.add_argument("--fake", action="store_true", help="use the built-in board emulator")
        return p

    p = add("fakeboard", cmd_fakeboard, "run the board emulator")
    p.add_argument("--leadoff-mask", type=lambda s: int(s, 0), default=0)
    p = add("setup", cmd_setup, "flash + Wi-Fi + acceptance test (guided)")
    p.add_argument("--no-flash", action="store_true")
    add("test", cmd_test, "acceptance test only")
    add("electrodes", cmd_electrodes, "live electrode contact check")
    add("scope", cmd_scope, "live 16-channel signal view")
    p = add("record", cmd_record, "guided recording session")
    p.add_argument("--minutes", type=float, default=12)
    p = add("synth", cmd_synth, "write synthetic sessions (pipeline test)")
    p.add_argument("--sessions", type=int, default=4)
    p.add_argument("--reps", type=int, default=15)
    p = add("train", cmd_train, "train + evaluate + pick 8 tokens")
    p.add_argument("sessions", nargs="*")
    p.add_argument("--model", default="lda", choices=["lda", "svm"])
    p.add_argument("--name", default="current")
    p.add_argument("--rank", type=int, default=0, help="greedy channel ranking up to N channels")
    p = add("engine", cmd_engine, "live recognition -> app")
    p.add_argument("--name", default="current")
    p = add("keysim", cmd_keysim, "keyboard as fake sensor -> app")
    p.add_argument("--accuracy", type=float, default=0.8)
    add("gaddy", cmd_gaddy, "real-EMG benchmark on the Gaddy dataset")
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
