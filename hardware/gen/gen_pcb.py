"""Build the SilentBand PCB from circuit.py: placement, planes, FreeRouting, zone fill.

Run with KiCad's bundled Python (see build.sh):  kpython gen_pcb.py [--no-route]
Output: hardware/out/silentband.kicad_pcb
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import circuit  # noqa: E402
import sexpr  # noqa: E402

OUT = os.path.join(circuit.REPO, "hardware/out")
PCB = os.path.join(OUT, "silentband.kicad_pcb")
FREEROUTING = os.path.join(circuit.REPO, "tools/bin/freerouting.jar")
FPLIB = os.path.join(sexpr.SHARED, "footprints")

W, H = 68.0, 46.0          # board size, mm
MM = pcbnew.FromMM
SPLIT = 36.5              # In2: AVDD plane for x < SPLIT (analog), +3V3 plane for x > SPLIT (digital)
POWER_NETS = {"GND", "+3V3", "AVDD", "VBUS", "BAT_IN", "VBAT", "VBAT_SW", "VSYS", "VSYS_A"}

# Fixed placements: ref -> (center x, center y, rotation deg). Everything else is pulled toward the
# pads it connects to and legalized (no courtyard overlap).
FIXED = {
    "J1": (4.6, 23.0, 0),        # electrode header, left edge
    "U1": (24.0, 12.5, 0),       # ADS1298 master (inputs on its left side)
    "U2": (24.0, 34.0, 0),       # ADS1298 slave
    "U3": (W - 12.75, 10.4, -90),  # ESP32-S3-WROOM-1 body center (25.5 x 18), antenna flush with right edge
    "J2": (35.0, 3.8, 90),       # IMU header, top edge
    "J3": (52.0, H - 3.6, 0),    # USB-C, bottom edge
    "J4": (40.0, H - 4.9, 0),    # LiPo JST-PH, bottom edge (opening faces the edge)
    "SW3": (W - 6.0, H - 2.2, 0),  # power slide switch, bottom edge
}


def load_fp(fpid: str):
    lib, name = fpid.split(":")
    fp = pcbnew.FootprintLoad(os.path.join(FPLIB, lib + ".pretty"), name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    return fp


def bbox(fp, margin=0.0):
    try:
        poly = fp.GetCourtyard(pcbnew.F_CrtYd)
        if poly.OutlineCount() == 0:
            raise ValueError
        b = poly.BBox()
        x0, y0, x1, y1 = b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()
    except Exception:
        b = fp.GetBoundingBox(False, False)
        x0, y0, x1, y1 = b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom()
    m = MM(margin)
    return (pcbnew.ToMM(x0 - m), pcbnew.ToMM(y0 - m), pcbnew.ToMM(x1 + m), pcbnew.ToMM(y1 + m))


def place_center(fp, x, y, rot):
    fp.SetOrientationDegrees(rot)
    fp.SetPosition(pcbnew.VECTOR2I_MM(0, 0))
    x0, y0, x1, y1 = bbox(fp)
    fp.SetPosition(pcbnew.VECTOR2I_MM(x - (x0 + x1) / 2, y - (y0 + y1) / 2))


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def legal(r, occupied):
    if r[0] < 0.4 or r[1] < 0.4 or r[2] > W - 0.4 or r[3] > H - 0.4:
        return False
    return not any(overlaps(r, o) for o in occupied)


def setup_board():
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(4)
    for lay in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        b.SetLayerType(lay, pcbnew.LT_POWER)
    ds = b.GetDesignSettings()
    ds.m_TrackMinWidth = MM(0.1)
    ds.m_MinClearance = MM(0.1)
    ds.m_ViasMinSize = MM(0.45)
    ds.m_MinThroughDrill = MM(0.3)
    ds.m_CopperEdgeClearance = MM(0.3)
    ds.m_HoleClearance = MM(0.2)
    ds.m_HoleToHoleMin = MM(0.25)
    ds.m_SolderMaskExpansion = MM(0.05)
    ns = ds.m_NetSettings
    dflt = ns.GetDefaultNetclass()
    dflt.SetTrackWidth(MM(0.15)); dflt.SetClearance(MM(0.13))
    dflt.SetViaDiameter(MM(0.6)); dflt.SetViaDrill(MM(0.3))
    pwr = pcbnew.NETCLASS("Power")
    pwr.SetTrackWidth(MM(0.25)); pwr.SetClearance(MM(0.13))
    pwr.SetViaDiameter(MM(0.6)); pwr.SetViaDrill(MM(0.3))
    ns.SetNetclass("Power", pwr)
    for n in POWER_NETS:
        ns.SetNetclassPatternAssignment(n, "Power")
    return b


def outline(b):
    pts = [(0, 0), (W, 0), (W, H), (0, H)]
    for i in range(4):
        s = pcbnew.PCB_SHAPE(b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I_MM(*pts[i])); s.SetEnd(pcbnew.VECTOR2I_MM(*pts[(i + 1) % 4]))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1))
        b.Add(s)


def zone(b, layer, net, rect, priority=0, keepout=False, layers=None, poly=None):
    z = pcbnew.ZONE(b)
    if keepout:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(True); z.SetDoNotAllowVias(True); z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowPads(False); z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        for lay in layers:
            ls.AddLayer(lay)
        z.SetLayerSet(ls)
    else:
        z.SetLayer(layer)
        z.SetNet(b.FindNet(net))
        z.SetAssignedPriority(priority)
        z.SetLocalClearance(MM(0.2))
        z.SetMinThickness(MM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(MM(0.25))
        z.SetThermalReliefSpokeWidth(MM(0.3))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    o = z.Outline()
    o.NewOutline()
    if poly is None:
        x0, y0, x1, y1 = rect
        poly = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    for x, y in poly:
        o.Append(MM(x), MM(y))
    b.Add(z)
    return z


def silk(b, text, x, y, size=0.8, rot=0, layer=pcbnew.F_SilkS):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(text)
    t.SetPosition(pcbnew.VECTOR2I_MM(x, y))
    t.SetTextSize(pcbnew.VECTOR2I_MM(size, size))
    t.SetTextThickness(MM(size * 0.15))
    t.SetTextAngleDegrees(rot)
    t.SetLayer(layer)
    b.Add(t)


ux, uy = FIXED["U3"][:2]
ANTENNA = [ux + 5.75, 0, W, uy + 10.5]  # x0 refined from the module pads in build()
VIA_D, VIA_DRILL, CLR, STUB = 0.5, 0.3, 0.135, 0.2  # 0.3 mm drill: no JLC small-via fee


# In2 split: AVDD under the analog half, +3V3 on the digital half plus a notch under each ADS's
# digital corner (DVDD pins 48/50/52 sit top-right of the chip).
NX = FIXED["U1"][0] + 2.0
NOTCH = [(NX, 0.3, FIXED["U1"][1] + 1.0), (NX, FIXED["U2"][1] - 7.0, FIXED["U2"][1] + 1.0)]
G = 0.25  # half gap between the two In2 nets
AVDD_POLY = [(0.3, 0.3), (NX - G, 0.3), (NX - G, NOTCH[0][2] + G), (SPLIT - G, NOTCH[0][2] + G),
             (SPLIT - G, NOTCH[1][1] - G), (NX - G, NOTCH[1][1] - G), (NX - G, NOTCH[1][2] + G),
             (SPLIT - G, NOTCH[1][2] + G), (SPLIT - G, H - 0.3), (0.3, H - 0.3)]
V33_POLY = [(NX + G, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (SPLIT + G, H - 0.3), (SPLIT + G, NOTCH[1][2] - G),
            (NX + G, NOTCH[1][2] - G), (NX + G, NOTCH[1][1] + G), (SPLIT + G, NOTCH[1][1] + G),
            (SPLIT + G, NOTCH[0][2] - G), (NX + G, NOTCH[0][2] - G)]


# Fast clock edges stay on F.Cu over the solid In1 GND plane: B.Cu references the split In2
# (AVDD/+3V3), so a clock there loses its return path at the split and runs under REF.
CLOCKS = ("CLK_M", "CLK_S", "SCLK")


def f_cu_only(dsn, nets):
    s = open(dsn).read()
    m = re.search(r"\(class kicad_default (.*?)\(circuit", s, re.S)
    assert m and all(n in m.group(1).split() for n in nets), "clock nets not in kicad_default"
    rest = " ".join(n for n in m.group(1).split() if n not in nets)
    s = s[:m.start(1)] + rest + "\n      " + s[m.end(1):]
    cls = (f"    (class clocks {' '.join(nets)}\n      (circuit\n        (use_layer F.Cu)\n      )\n"
           "      (rule\n        (width 150)\n        (clearance 130)\n      )\n    )\n")
    i = s.index("    (class kicad_default")
    open(dsn, "w").write(s[:i] + cls + s[i:])


def in_poly(x, y, poly):
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def plane_at(x, y, m=0.6):
    """In2 net under (x, y) with margin m on all sides, else None."""
    for net, poly in (("AVDD", AVDD_POLY), ("+3V3", V33_POLY)):
        if all(in_poly(x + dx, y + dy, poly) for dx in (-m, 0, m) for dy in (-m, 0, m)):
            return net
    return None


def plane_net(net, x):
    return net in ("GND", "AVDD", "+3V3")


def fanout(b, fps):
    """Short locked stub + via from every SMD plane-net pad to its plane, placed clear of other copper."""
    obst = []  # (x0, y0, x1, y1, net) pad rectangles
    for fp in fps.values():
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            obst.append((pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetRight()),
                         pcbnew.ToMM(bb.GetBottom()), pad.GetNetname()))
    vias = []  # (x, y, net)
    stubs = []  # (x0, y0, x1, y1, net)

    def seg_dist(x, y, s):
        x0, y0, x1, y1 = s[:4]
        L = (x1 - x0) ** 2 + (y1 - y0) ** 2
        t = 0 if L == 0 else max(0, min(1, ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / L))
        return math.hypot(x - x0 - t * (x1 - x0), y - y0 - t * (y1 - y0))
    u3 = (ux - 13.0, uy - 9.25, ux + 13.0, uy + 9.25)

    def rect_dist(x, y, r):
        dx = max(r[0] - x, 0, x - r[2]); dy = max(r[1] - y, 0, y - r[3])
        return math.hypot(dx, dy)

    def clear(x, y, rad, net, own):
        if not (0.8 < x < W - 0.8 and 0.8 < y < H - 0.8):
            return False
        if ANTENNA[0] - rad - 0.3 < x and y < ANTENNA[3] + rad + 0.3:
            return False
        for r in obst:
            if r is own:
                continue
            if rect_dist(x, y, r) < rad + CLR:
                return False
        return all(math.hypot(x - vx, y - vy) >= rad + VIA_D / 2 + CLR for vx, vy, vn in vias) and \
            all(sn == net or seg_dist(x, y, sg) >= rad + STUB / 2 + CLR for sg in stubs for sn in [sg[4]])

    n = 0
    for ref, fp in sorted(fps.items()):
        if ref == "J1":
            continue
        c = fp.GetPosition()
        cx, cy = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)
        for pad in fp.Pads():
            if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or not pad.IsOnLayer(pcbnew.F_Cu):
                continue
            p = pad.GetPosition()
            px, py = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
            net = pad.GetNetname()
            if not plane_net(net, px) or (ref == "U3" and pad.GetNumber() == "41"):
                continue  # U3 pad 41 has its own via array
            own = next(r for r in obst if abs((r[0] + r[2]) / 2 - px) < 1e-3 and abs((r[1] + r[3]) / 2 - py) < 1e-3
                       and r[4] == net)
            # outward direction: along the axis on which the pad sits farther from the footprint center
            dx, dy = px - cx, py - cy
            if ref.startswith("U") and fp.GetPadCount() > 8:
                d = (math.copysign(1, dx), 0) if abs(dx) > abs(dy) else (0, math.copysign(1, dy))
                dirs = [(-d[0], -d[1]), d]  # inward under the body first: keeps the escape side free
            else:
                dirs = [(math.copysign(1, dx or 1), 0), (0, math.copysign(1, dy or 1)),
                        (-math.copysign(1, dx or 1), 0), (0, -math.copysign(1, dy or 1))]
            hw = (own[2] - own[0]) / 2; hh = (own[3] - own[1]) / 2
            spot = None
            for k in range(0, 14):
                for ux_, uy_ in dirs:
                    base = (hw if ux_ else hh) + VIA_D / 2 + 0.1 + k * 0.2
                    for side in (0, 0.35, -0.35, 0.7, -0.7):
                        vx = px + ux_ * base + (side if uy_ else 0)
                        vy = py + uy_ * base + (side if ux_ else 0)
                        if in_rect(vx, vy, u3) and ref != "U3":
                            continue
                        if not clear(vx, vy, VIA_D / 2, net, own):
                            continue
                        if net != "GND" and plane_at(vx, vy) != net:
                            continue
                        # stub (0.25 wide) must clear other-net pads and vias
                        ok = True
                        steps = max(2, int(math.hypot(vx - px, vy - py) / 0.1))
                        for i in range(steps + 1):
                            t = i / steps
                            sx, sy = px + (vx - px) * t, py + (vy - py) * t
                            if rect_dist(sx, sy, own) == 0:
                                continue
                            if sx > ANTENNA[0] - 0.4 and sy < ANTENNA[3] + 0.4:
                                ok = False
                                break
                            if any(r[4] != net and rect_dist(sx, sy, r) < STUB / 2 + CLR for r in obst) or \
                               any(vn != net and math.hypot(sx - qx, sy - qy) < STUB / 2 + VIA_D / 2 + CLR for qx, qy, vn in vias) or \
                               any(sg[4] != net and seg_dist(sx, sy, sg) < STUB + CLR for sg in stubs):
                                ok = False
                                break
                        if ok:
                            spot = (vx, vy)
                            break
                    if spot:
                        break
                if spot:
                    break
            if spot is None:
                print(f"no fanout for {ref}.{pad.GetNumber()} ({net})")
                continue
            vx, vy = spot
            ni = b.FindNet(net)
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(p); t.SetEnd(pcbnew.VECTOR2I_MM(vx, vy)); t.SetWidth(MM(STUB))
            t.SetLayer(pcbnew.F_Cu); t.SetNet(ni); t.SetLocked(True)
            b.Add(t)
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I_MM(vx, vy)); v.SetWidth(MM(VIA_D)); v.SetDrill(MM(VIA_DRILL))
            v.SetNet(ni); v.SetLocked(True)
            b.Add(v)
            vias.append((vx, vy, net))
            stubs.append((px, py, vx, vy, net))
            n += 1
    return n


def in_rect(x, y, r):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def write_project():
    """Design rules and net classes live in the .kicad_pro (DRC and the fab review read them)."""
    cls = lambda name, tw, clr, vd, vdr, prio: {
        "name": name, "track_width": tw, "clearance": clr, "via_diameter": vd, "via_drill": vdr,
        "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.2,
        "diff_pair_via_gap": 0.25, "bus_width": 12, "wire_width": 6, "line_style": 0, "priority": prio,
        "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)"}
    pro = {
        "meta": {"filename": "silentband.kicad_pro", "version": 3},
        "board": {"design_settings": {
            "rules": {  # JLCPCB 4-layer capabilities, with margin
                "min_clearance": 0.1, "min_track_width": 0.1, "min_connection": 0.0,
                "min_via_diameter": 0.45, "min_via_annular_width": 0.075, "min_through_hole_diameter": 0.3,
                "min_hole_clearance": 0.2, "min_hole_to_hole": 0.25, "min_copper_edge_clearance": 0.3,
                "min_silk_clearance": 0.0, "min_text_height": 0.8, "min_text_thickness": 0.12,
                "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1, "min_groove_width": 0.0,
                "min_resolved_spokes": 1, "solder_mask_to_copper_clearance": 0.0, "max_error": 0.005,
                "allow_blind_buried_vias": False, "allow_microvias": False, "use_height_for_length_calcs": True},
            "rule_severities": {"lib_footprint_issues": "ignore", "lib_footprint_mismatch": "ignore",
                                "silk_overlap": "warning", "silk_over_copper": "warning",
                                "silk_edge_clearance": "warning"},
        }},
        "net_settings": {
            "meta": {"version": 4},
            "classes": [cls("Default", 0.15, 0.13, 0.6, 0.3, 2147483647), cls("Power", 0.25, 0.13, 0.6, 0.3, 0)],
            "netclass_patterns": [{"netclass": "Power", "pattern": n} for n in sorted(POWER_NETS)],
            "net_colors": None, "netclass_assignments": None,
        },
        "pcbnew": {"page_layout_descr_file": ""},
    }
    with open(PCB.replace(".kicad_pcb", ".kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)


def build(route=True):
    os.makedirs(OUT, exist_ok=True)
    parts = circuit.build()
    b = setup_board()
    netinfo = {}
    for n in sorted(circuit.nets(parts)):
        ni = pcbnew.NETINFO_ITEM(b, n)
        b.Add(ni)
        netinfo[n] = ni
    fps = {}
    for p in parts:
        fp = load_fp(p.footprint)
        fp.SetReference(p.ref)
        fp.SetValue(p.value)
        fp.SetFPID(pcbnew.LIB_ID(*p.footprint.split(":")))
        for pad in fp.Pads():
            n = p.pads.get(pad.GetNumber())
            if n == "":
                continue  # intentional no-connect
            if n:
                pad.SetNet(netinfo[n])
            elif pad.GetNumber() and pad.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                raise SystemExit(f"{p.ref} pad {pad.GetNumber()} unassigned")
        big = p.ref in FIXED and p.ref != "U3"  # U3 ref would sit on the board edge
        fp.Reference().SetVisible(big)
        fp.Value().SetVisible(False)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I_MM(0.8, 0.8))
        fp.Reference().SetTextThickness(MM(0.12))
        b.Add(fp)
        fps[p.ref] = fp
    for pad_ref, p in ((p.ref, p) for p in parts):  # all circuit pads must exist on the footprint
        names = {pd.GetNumber() for pd in fps[pad_ref].Pads()}
        missing = set(p.pads) - names
        if missing:
            raise SystemExit(f"{pad_ref}: pads {missing} not in footprint {p.footprint}")

    # ---- placement ----
    occupied = []
    for ref, (x, y, r) in FIXED.items():
        if ref == "U3":  # origin = body center; its 48 mm courtyard/rule area includes antenna clearance
            fp = fps[ref]
            fp.SetOrientationDegrees(r)
            fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
            for z in list(fp.Zones()):
                fp.Remove(z)
            for pd in fp.Pads():  # thermal vias under pad 41: 0.2 -> 0.3 mm drill (standard fab tier)
                if pd.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and pd.GetDrillSize().x < MM(0.3):
                    pd.SetDrillSize(pcbnew.VECTOR2I_MM(0.3, 0.3)); pd.SetSize(pcbnew.VECTOR2I_MM(0.6, 0.6))
            for g in list(fp.GraphicalItems()):  # courtyard includes antenna clearance; use the body
                if g.GetLayer() == pcbnew.F_CrtYd:
                    fp.Remove(g)
            cy = pcbnew.PCB_SHAPE(fp)
            cy.SetShape(pcbnew.SHAPE_T_RECT)
            cy.SetStart(pcbnew.VECTOR2I_MM(x - 13.0, y - 9.25)); cy.SetEnd(pcbnew.VECTOR2I_MM(x + 13.0, y + 9.25))
            cy.SetLayer(pcbnew.F_CrtYd); cy.SetWidth(MM(0.05))
            fp.Add(cy)
            occupied.append((x - 13.05, y - 9.3, x + 13.05, y + 9.3))
            continue
        place_center(fps[ref], x, y, r)
        occupied.append(bbox(fps[ref], 0.3))
    ANTENNA[0] = max(pcbnew.ToMM(pd.GetBoundingBox().GetRight()) for pd in fps["U3"].Pads()) + 0.3
    occupied.append((ANTENNA[0] - 0.3, ANTENNA[1], ANTENNA[2], ANTENNA[3] + 0.3))
    placed = set(FIXED)
    anchors = {"ads1": "U1", "ads2": "U2", "mcu": "U3"}
    spread: dict = {}
    unplaced: list = []

    def target(p):
        pts = []
        prefer = anchors.get(p.group)
        for n in p.pads.values():
            if n == "GND" or n.startswith("NC"):
                continue
            for r2, pad in circuit.nets(parts)[n]:
                if r2 in placed and r2 != p.ref and (prefer is None or r2 == prefer or n.startswith(("EL", "IN"))):
                    pos = fps[r2].FindPadByNumber(pad).GetPosition()
                    pts.append((pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))
        if p.group == "aldo":
            return (33.0, 23.0)
        if not pts:
            gx = {"power": (40, 33), "usb": (52, 38), "imu": (40, 5)}.get(p.group, (W / 2, H / 2))
            return gx
        if prefer and p.value in ("100n", "1u", "10u", "22u"):
            # decoupling: spread caps of the same net over that net's anchor pads, one pad each
            key = (prefer, tuple(sorted(p.pads.values())))
            k = spread.get(key, 0)
            spread[key] = k + 1
            return sorted(pts)[k % len(pts)]
        return (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))

    order = sorted((p for p in parts if p.ref not in placed),
                   key=lambda p: (0 if p.group.startswith("ads") else 1 if p.group.startswith("afe") else 2,
                                  p.value not in ("100n", "1u", "22u", "10u")))
    for p in order:
        fp = fps[p.ref]
        tx, ty = target(p)
        best = None
        for rot in (0, 90):
            place_center(fp, 0, 0, rot)
            x0, y0, x1, y1 = bbox(fp, 0.15)
            w, h = x1 - x0, y1 - y0
            for rad in [i * 0.25 for i in range(0, 120)]:
                ring = [(0, 0)] if rad == 0 else [(rad * math.cos(a), rad * math.sin(a))
                                                  for a in [k * 2 * math.pi / max(8, int(rad * 12)) for k in range(max(8, int(rad * 12)))]]
                hit = None
                for dx, dy in ring:
                    cx, cy = tx + dx, ty + dy
                    r = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                    if legal(r, occupied):
                        hit = (rad, rot, cx, cy, r)
                        break
                if hit:
                    if best is None or hit[0] < best[0]:
                        best = hit
                    break
        if best is None:
            print(f"WARNING: no room for {p.ref}")
            unplaced.append(p.ref)
            continue
        _, rot, cx, cy, r = best
        place_center(fp, cx, cy, rot)
        occupied.append(r)
        placed.add(p.ref)

    # ---- outline, planes, silk ----
    outline(b)
    zone(b, pcbnew.In1_Cu, "GND", (0.3, 0.3, W - 0.3, H - 0.3))
    zone(b, pcbnew.In2_Cu, "AVDD", None, poly=AVDD_POLY)
    zone(b, pcbnew.In2_Cu, "+3V3", None, poly=V33_POLY)
    allcu = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    zone(b, None, None, ANTENNA, keepout=True, layers=allcu)  # no copper under/around the antenna
    e = 0.45  # routing keepout ring along the board edge (pads allowed)
    for r in ((0, 0, W, e), (0, H - e, W, H), (0, 0, e, H), (W - e, 0, W, H)):
        zone(b, None, None, r, keepout=True, layers=[pcbnew.F_Cu, pcbnew.B_Cu])
    nvia = fanout(b, fps)
    j1 = fps["J1"]
    for i in range(1, 21):
        pos = j1.FindPadByNumber(str(i)).GetPosition()
        x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
        lab = str(i) if i <= 16 else ("REF" if i <= 18 else "RLD")
        silk(b, lab, x + (-3.6 if i % 2 else 3.6), y, 0.8)
    silk(b, "SilentBand v1", 30, H - 1.2, 1.0)
    jb = fps["J4"]
    for pad, lab in (("1", "+"), ("2", "-")):
        pos = jb.FindPadByNumber(pad).GetPosition()
        silk(b, lab, pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) - 2.6, 1.2)

    pcbnew.SaveBoard(PCB, b)
    if route:
        dsn, ses = PCB.replace(".kicad_pcb", ".dsn"), PCB.replace(".kicad_pcb", ".ses")
        pcbnew.ExportSpecctraDSN(b, dsn)
        f_cu_only(dsn, CLOCKS)
        subprocess.run(["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", "100", "-host", "KiCad"],
                       check=True, stdout=subprocess.DEVNULL if "-q" in sys.argv else None)
        pcbnew.ImportSpecctraSES(b, ses)
        for t in b.GetTracks():  # FreeRouting necks down at fine-pitch pads; fab minimum is 0.1 mm
            if t.GetClass() == "PCB_TRACK" and t.GetWidth() < MM(0.1):
                t.SetWidth(MM(0.1))
    zone(b, pcbnew.B_Cu, "GND", (0.3, 0.3, W - 0.3, H - 0.3))  # poured after routing, stitches GND
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(PCB, b)
    write_project()
    print("saved", PCB, f"{len(parts)} parts, {nvia} fanout vias, {len(b.GetTracks())} track/via items")


if __name__ == "__main__":
    build(route="--no-route" not in sys.argv)
