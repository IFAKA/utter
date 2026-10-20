import threading

import numpy as np
import pytest

from utter import dataset, engine, protocol as P, train
from utter.fakeboard import FakeBoard
from utter.stream import Board

TOK = P.load_tokens()["candidates"]


def test_protocol_roundtrip():
    codes = np.random.default_rng(0).integers(-2**23, 2**23, (20, 16)).astype(np.int32)
    pkt = P.Packet(7, 140, 2000, P.FLAG_TEST, 0x5, 0xA, codes, imu=(1, -2, 3, -4, 5, -6))
    out = P.decode(P.encode(pkt))
    assert np.array_equal(out.codes, codes)
    assert (out.seq, out.first_sample, out.fs, out.leadoff_p, out.leadoff_n, out.imu) == \
        (7, 140, 2000, 5, 10, (1, -2, 3, -4, 5, -6))
    assert out.flags & P.FLAG_TEST and out.flags & P.FLAG_IMU


@pytest.fixture(scope="module")
def sessions(tmp_path_factory):
    d = tmp_path_factory.mktemp("s")
    return [dataset.synth_session(d / f"s{i}", TOK, reps=10, day=i // 2, session_seed=100 + i) for i in range(4)]


def test_offline_and_live_agree(sessions):
    t = dataset.load_trials(sessions)
    assert train.within_session(t) > 0.8
    keep, acc = train.pick_tokens(t, 8)
    assert len(keep) == 8 and acc > 0.8
    m = np.isin(t.y, keep + ["rest"])
    sub = dataset.Trials(t.X[m], t.y[m], t.group[m], t.day[m], t.raw_label[m])
    path = train.fit_save(sub, "pytest", {"mapping": dict(zip(keep, P.load_tokens()["actions"]))})
    emg, _, events = dataset.load_session(sessions[3])
    rec = engine.Recognizer(path, 2000, 16)
    dets = []
    for i in range(0, len(emg), 20):
        dets += [(i, lab) for lab, _, _ in rec.push(emg[i:i + 20].astype(float))]
    hits = n = false = 0
    for ev in events:
        got = [lab for i, lab in dets if ev["sample"] <= i < ev["sample"] + 4000]
        if ev["label"] in keep:
            n += 1
            hits += got[:1] == [ev["label"]]
        elif ev["label"] in dataset.REST_LABELS:
            false += bool(got)
    assert hits / n > 0.75
    assert rec.notices.count("too_fast") <= n // 10  # one gesture must not read as two
    assert false <= 2


def test_fakeboard_over_udp():
    fb = FakeBoard(ctrl_port=47711)
    threading.Thread(target=fb.serve, daemon=True).start()
    b = Board("127.0.0.1", data_port=47712, ctrl_port=47711)
    assert b.cmd(cmd="info")["chip_ids"] == [0x92, 0x92]
    b.start(fs=2000)
    assert b.wait_samples(4000, timeout=5)
    b.stop()
    assert b.lost == 0
    assert b.last(1.0).shape == (2000, 16)



def test_neckband_pairs_rank():
    from utter import dsp, neckband
    assert len(neckband.SITES) == 16 and len(set(neckband.PAIRS)) == len(neckband.PAIRS)
    assert all(0 <= i < 16 and 0 <= j < 16 for i, j in neckband.PAIRS)
    seg = np.random.default_rng(0).standard_normal((2000, 16))
    assert len(dsp.features(seg, 2000, neckband.PAIRS)) == len(dsp.feature_names(16, neckband.PAIRS))


def test_assign_actions_keeps_confused_pair_off_accept():
    labels = ["a", "b", "c", "d", "e", "f", "g", "h", "rest"]
    cm = np.eye(9) * 90 + 1
    cm[0, 1] = cm[1, 0] = 40  # a and b are often confused
    m = train.assign_actions(labels, cm, ["G1", "G2", "G3", "G4", "NEXT", "ACCEPT", "BACK", "WAKE"])
    assert "ACCEPT" not in (m["a"], m["b"]) and "NEXT" not in (m["a"], m["b"])
