"""SilentBand v1 pod: back-of-neck housing for hardware/out/silentband.kicad_pcb (68 x 46 mm, no holes).

All feature positions are KiCad board coordinates (mm, origin top-left, y down) so they can be checked
against the PCB directly; k(x, y) maps them to model space (y up). Run:

    python3 -m pip install manifold3d numpy   # Python <= 3.13 has wheels
    python3 hardware/enclosure/pod.py          # writes out/pod_base.stl, out/pod_lid.stl, checks fit

The check builds every footprint on the board as a box (pads + known body height) and fails if any
part touches the housing, so a PCB change that collides with the shell is caught before printing.
"""
import math
import re
import struct
import sys
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

HERE = Path(__file__).resolve().parent
PCB = HERE.parent / "out" / "silentband.kicad_pcb"
OUT = HERE / "out"
SEG = 48

BW, BH, BT = 68.0, 46.0, 1.6     # board
CL = 0.5                          # board-to-wall clearance
WALL, FLOOR, LID = 2.0, 1.6, 1.8
BATT = (40.0, 30.0, 5.0)          # 503040 1S LiPo, protected, JST-PH 2.0
ZB = FLOOR + BATT[2] + 0.8        # board underside (0.8 mm for cell swelling)
ZT = ZB + BT                      # board top
TOP = ZT + 6.6                    # lid underside (tallest part off-header: JST-PH 6 mm)
BOSS_R, PILOT, SCREW = 2.9, 1.7, 2.4   # 4x M2x10 self-tapping, pan head
STRAP = 26.0                      # slot for a 25 mm strap
WIRE = (35.0, 45.0)               # pocket for the J4 battery plug: J4 mates towards the board edge
POCKET = 7.5                      # plug (PHR-2) + lead bend beyond the cavity wall
PLUG = (37.0, 43.0, 4.6)          # PHR-2 plug: x range, height
PEGS = [(1.3, 1.3), (1.3, 44.7), (12, 1.3), (66.7, 26), (66.7, 36)]  # board-edge spots with no parts


def k(x, y):
    return (x, BH - y)


def box(x0, y0, z0, x1, y1, z1):
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def cyl(x, y, z0, h, d):
    return Manifold.cylinder(h, d / 2, circular_segments=SEG).translate((x, y, z0))


BOSSES = [k(-2.6, -2.6), k(BW + 2.6, -2.6), k(-2.6, BH + 2.6), k(BW + 2.6, BH + 2.6)]
CAVITY = CrossSection.square((BW + 2 * CL, BH + 2 * CL)).translate((-CL, -CL))


def outline():
    shell = CAVITY.offset(WALL, JoinType.Round, circular_segments=SEG)
    pts = CrossSection.batch_hull([shell] + [CrossSection.circle(BOSS_R, SEG).translate(b) for b in BOSSES])
    bump = CrossSection.square((WIRE[1] - WIRE[0] + 2 * WALL, POCKET + WALL)).translate((WIRE[0] - WALL, -CL - POCKET - WALL))
    bump = bump.offset(1.5, JoinType.Round, circular_segments=SEG).offset(-1.5, JoinType.Round, circular_segments=SEG)
    return pts + bump


def edge_cut(x, w, zc, h, recess=None):
    """Opening through the wall on the KiCad y=46 edge (model y=0)."""
    m = box(x - w / 2, -CL - WALL - 1, zc - h / 2, x + w / 2, -CL + 1, zc + h / 2)
    if recess:
        rw, rh = recess
        m += box(x - rw / 2, -CL - WALL - 3, zc - rh / 2, x + rw / 2, -CL - 1.0, zc + rh / 2)
    return m


def lugs():
    """Strap lugs on the short ends: (solid, slot) pairs."""
    for s in (-1, 1):
        x0 = -CL - WALL - 9 if s < 0 else BW + CL + WALL - 1
        sx = x0 + 2.5 if s < 0 else x0 + 10 - 2.5 - 3.4
        yield (box(x0, BH / 2 - STRAP / 2 - 3, 0, x0 + 10, BH / 2 + STRAP / 2 + 3, 6),
               box(sx, BH / 2 - STRAP / 2, -1, sx + 3.4, BH / 2 + STRAP / 2, 7))


def build_base():
    m = outline().extrude(TOP)
    cuts = [CAVITY.extrude(TOP).translate((0, 0, FLOOR))]
    for solid, slot in lugs():
        m += solid
        cuts.append(slot)
    cuts.append(box(WIRE[0], -CL - POCKET, FLOOR, WIRE[1], -CL + 0.1, TOP + 1))   # battery plug pocket + lead channel
    cuts.append(edge_cut(52, 9.8, ZT + 1.65, 4.0, recess=(12.8, 7.2)))         # USB-C J3 + plug overmold
    cuts.append(edge_cut(62, 9.0, ZT + 0.9, 3.4))                             # power slide switch SW3
    cuts += [cyl(*b, TOP - 11, 12, PILOT) for b in BOSSES]
    for c in cuts:
        m -= c
    ledge = (CAVITY - CAVITY.offset(-1.2, JoinType.Miter)).extrude(ZB - FLOOR).translate((0, 0, FLOOR))
    ledge -= box(46, -CL - 0.1, 0, 58, 1.5, ZB + 1)                           # under USB-C shell tabs
    ledge -= box(WIRE[0], -CL - 0.1, 0, WIRE[1], 1.5, ZB + 1)
    x0, y0 = BW / 2 - BATT[0] / 2 - 1.7, BH / 2 - BATT[1] / 2 - 1.7
    rail = box(x0, y0, FLOOR, x0 + BATT[0] + 3.4, y0 + BATT[1] + 3.4, FLOOR + 1.2)
    rail -= box(x0 + 1.2, y0 + 1.2, 0, x0 + BATT[0] + 2.2, y0 + BATT[1] + 2.2, 9)
    rail -= box(x0 - 1, BH / 2 - 4, 0, x0 + 3, BH / 2 + 4, 9)                # lead exit
    return m + ledge + rail


def build_lid():
    m = outline().extrude(LID).translate((0, 0, TOP))
    cuts = [cyl(*b, TOP - 1, LID + 2, SCREW) for b in BOSSES]
    x, y = k(-0.5, 38.8)
    cuts.append(box(x, y, TOP - 1, x + 10.7, y + 31.6, TOP + LID + 1))      # J1: 2x10 IDC socket + ribbon
    x, y = k(29, 6.1)
    cuts.append(box(x, y, TOP - 1, x + 12, y + 4.6, TOP + LID + 1))         # J2: 1x4 IMU socket
    cuts += [cyl(*k(*p), TOP - 1, LID + 2, 2.2) for p in [(34.65, 25.67), (58.0, 31.63)]]   # LEDs D1 D2
    cuts += [cyl(*k(*p), TOP - 1, LID + 2, 1.8) for p in [(54.71, 24.67), (45.16, 22.72)]]  # RESET BOOT
    for c in cuts:
        m -= c
    for p in PEGS:
        x, y = k(*p)
        m += box(x - 1.25, y - 1.25, ZT + 0.1, x + 1.25, y + 1.25, TOP)
    return m


# Body heights above the board top (mm); bodies larger than their pads are given explicitly.
HEIGHT = {"J1": 8.5, "J2": 8.5, "J4": 6.0, "J3": 3.3, "U3": 3.2, "SW3": 1.6, "SW1": 1.5, "SW2": 1.5,
          "U1": 1.2, "U2": 1.2}
BODY = {"U3": (42.4, 1.4, 68.0, 19.4)}          # ESP32-S3-WROOM-1 module, antenna at the board edge
OPEN_TOP = {"J1", "J2"}                          # mate through lid openings; checked below the lid only


def parts():
    s = PCB.read_text()
    for f in re.split(r"\n\t\(footprint ", s)[1:]:
        ref = re.search(r'"Reference" "([^"]+)"', f).group(1)
        ax, ay, *r = map(float, re.search(r"\(at ([^)]*)\)", f).group(1).split())
        a = math.radians(r[0] if r else 0)
        xs, ys = [], []
        def put(px, py):
            X, Y = ax + px * math.cos(a) + py * math.sin(a), ay - px * math.sin(a) + py * math.cos(a)
            xs.append(X)
            ys.append(Y)
        for p in re.finditer(r'\(fp_(?:line|rect)\s*\(start ([^)]*)\)\s*\(end ([^)]*)\)(?:(?!\(fp_).)*?\(layer "F\.Fab"\)', f, re.S):
            for q in p.groups():
                put(*map(float, q.split()))
        for p in re.finditer(r'\(pad "[^"]*" \w+ \w+\s*\(at ([^)]*)\)\s*\(size ([^)]*)\)', f):
            px, py, *_ = map(float, p.group(1).split())
            w, h = map(float, p.group(2).split())
            if round(math.degrees(a)) % 180:
                w, h = h, w
            X, Y = ax + px * math.cos(a) + py * math.sin(a), ay - px * math.sin(a) + py * math.cos(a)
            xs += [X - w / 2, X + w / 2]
            ys += [Y - h / 2, Y + h / 2]
        if not xs:
            continue
        x0, y0, x1, y1 = BODY.get(ref, (min(xs), min(ys), max(xs), max(ys)))
        yield ref, (x0, BH - y1, x1, BH - y0), HEIGHT.get(ref, 1.0)


def check(b, l):
    bad = []
    board = box(0, 0, ZB, BW, BH, ZT)
    if (box(0, 0, ZB + 1e-3, BW, BH, ZT) ^ b).volume() > 1e-3:
        bad.append("board overlaps base")
    if (board ^ l).volume() > 1e-3:
        bad.append("lid pegs dig into board")
    for ref, (x0, y0, x1, y1), h in parts():
        top = min(ZT + h, TOP - 1e-3) if ref in OPEN_TOP else ZT + h
        part = box(x0, y0, ZT, x1, y1, top)
        for name, m in (("base", b), ("lid", l)):
            if (part ^ m).volume() > 1e-3:
                bad.append(f"{ref} hits {name}")
    x0, x1, h = PLUG
    plug = box(x0, -CL - POCKET + 0.3, ZT, x1, BH - 45.5, ZT + h)          # J4 mating face at KiCad y 45.5
    for name, m in (("base", b), ("lid", l)):
        if (plug ^ m).volume() > 1e-3:
            bad.append(f"battery plug hits {name}")
    cell = box(BW / 2 - BATT[0] / 2, BH / 2 - BATT[1] / 2, FLOOR, BW / 2 + BATT[0] / 2, BH / 2 + BATT[1] / 2, FLOOR + BATT[2])
    if (cell ^ b).volume() > 1e-3:
        bad.append("battery does not fit")
    return bad


def stl(m, path):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3]
    t = np.asarray(mesh.tri_verts)
    tri = v[t]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as fh:
        fh.write(b"SilentBand pod".ljust(80, b"\0") + struct.pack("<I", len(t)))
        fh.write(rec.tobytes())


if __name__ == "__main__":
    b, l = build_base(), build_lid()
    bad = check(b, l)
    for m, name in ((b, "base"), (l, "lid")):
        lo, hi = np.array(m.bounding_box()[:3]), np.array(m.bounding_box()[3:])
        print(f"{name}: {m.volume() / 1000:.1f} cm3, genus {m.genus()}, {np.round(hi - lo, 1)} mm")
    OUT.mkdir(exist_ok=True)
    stl(b, OUT / "pod_base.stl")
    # lid printed outer face down
    stl(l.mirror((0, 0, 1)).translate((0, 0, TOP + LID)), OUT / "pod_lid.stl")
    print("FAIL: " + "; ".join(bad) if bad else "fit check: OK (board, battery and all parts clear)")
    sys.exit(1 if bad else 0)
