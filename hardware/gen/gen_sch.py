"""Generate the SilentBand schematic from circuit.py (one sheet, every pin tied to a global net label).

Run with any Python 3.9+:  python3 gen_sch.py
Output: hardware/out/silentband.kicad_sch (then ERC + netlist parity via build.sh)
Checks: every symbol pin has a pad in circuit.py (pin numbers == pad numbers) and vice versa
(footprint-only pads such as switch shells are listed).
"""
from __future__ import annotations

import os
import sys
import uuid as _uuid

sys.path.insert(0, os.path.dirname(__file__))
import circuit  # noqa: E402
import sexpr  # noqa: E402
from sexpr import Sym  # noqa: E402

OUT = os.path.join(circuit.REPO, "hardware/out")
SCH = os.path.join(OUT, "silentband.kicad_sch")
G = 2.54
ROOT = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "silentband/root"))
FLAG_NETS = ["GND", "VBUS", "VBAT_SW", "VSYS", "VSYS_A"]  # nets fed by connectors/switches
GROUP_TITLES = {"conn": "Electrode header", "afe1": "Input filters U1 (IN1-8, REF, RLD)",
                "afe2": "Input filters U2 (IN9-16)", "ads1": "ADS1298 master (clock out, RLD)",
                "ads2": "ADS1298 slave", "mcu": "ESP32-S3 + buttons + LED", "imu": "IMU header (I2C)",
                "usb": "USB-C + ESD", "power": "LiPo, charger, power path, 3.3 V", "aldo": "Analog 3.0 V LDO"}


def uid(*key) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, "silentband/" + "/".join(map(str, key))))


def snap(v: float) -> float:
    return round(v / G) * G


def font(hide=False, justify=None):
    e = [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]
    if justify:
        e.append([Sym("justify"), Sym(justify)])
    if hide:
        e.append([Sym("hide"), Sym("yes")])
    return e


def prop(name, value, x, y, hide=False, angle=0):
    return [Sym("property"), name, value, [Sym("at"), round(x, 2), round(y, 2), angle], font(hide)]


def extent(sym):
    """Symbol body + pins bounding box in schematic orientation (y down)."""
    xs, ys = [], []
    for p in sexpr.pins(sym):
        xs.append(p["x"]); ys.append(-p["y"])
    for sub in sexpr.find(sym, "symbol"):
        for r in sexpr.find(sub, "rectangle"):
            s, e = sexpr.first(r, "start"), sexpr.first(r, "end")
            xs += [float(s[1]), float(e[1])]; ys += [-float(s[2]), -float(e[2])]
    if not xs:
        return (-G, -G, G, G)
    return (min(xs), min(ys), max(xs), max(ys))


def label_len(net):
    return 1.0 * len(net) + 3.0


def main():
    parts = circuit.build()
    lib = {}
    problems = []
    for p in parts:
        if p.symbol not in lib:
            lib[p.symbol] = sexpr.symbol(p.symbol)
        pins = {q["number"] for q in sexpr.pins(lib[p.symbol])}
        missing = pins - set(p.pads)
        if missing:
            problems.append(f"{p.ref}: symbol pins {sorted(missing)} have no pad/net in circuit.py")
        extra = set(p.pads) - pins
        if extra:
            print(f"note: {p.ref} footprint-only pads {sorted(extra)} -> {sorted({p.pads[x] for x in extra})}")
    if problems:
        raise SystemExit("\n".join(problems))
    flag = sexpr.symbol("power:PWR_FLAG")
    lib["power:PWR_FLAG"] = flag

    # ---- layout: groups packed in shelves, parts in rows inside each group ----
    groups: dict[str, list] = {}
    for p in parts:
        groups.setdefault(p.group, []).append(p)
    items, labels, ncs, texts = [], [], [], []
    PAPER_W = 820.0
    gx, gy, shelf_h = 15.0, 20.0, 0.0
    for gname, gparts in groups.items():
        cells = []
        for p in gparts:
            x0, y0, x1, y1 = extent(lib[p.symbol])
            pins = sexpr.pins(lib[p.symbol])
            lw = max([label_len(p.pads.get(q["number"], "")) for q in pins] + [0])
            cells.append((p, x0 - lw, y0 - 5.0, x1 + lw, y1 + 4.0))
        maxw = max(c[3] - c[1] for c in cells)
        row_w = max(maxw, min(260.0, sum(c[3] - c[1] for c in cells)))
        # pack cells in rows of width row_w
        cx, cy, row_h, block_w = 0.0, 8.0, 0.0, 0.0
        placed = []
        for p, x0, y0, x1, y1 in cells:
            w, h = x1 - x0, y1 - y0
            if cx > 0 and cx + w > row_w:
                cx, cy, row_h = 0.0, cy + row_h, 0.0
            placed.append((p, cx - x0, cy - y0))
            cx += w; row_h = max(row_h, h); block_w = max(block_w, cx)
        block_h = cy + row_h
        if gx > 15.0 and gx + block_w > PAPER_W:
            gx, gy, shelf_h = 15.0, gy + shelf_h + 15.0, 0.0
        texts.append((GROUP_TITLES.get(gname, gname), gx, gy + 3.0))
        for p, ox, oy in placed:
            items.append((p, snap(gx + ox), snap(gy + oy)))
        gx += block_w + 20.0
        shelf_h = max(shelf_h, block_h)
    paper_h = gy + shelf_h + 20.0

    # ---- emit ----
    sch = [Sym("kicad_sch"), [Sym("version"), 20250114], [Sym("generator"), "silentband_gen"],
           [Sym("generator_version"), "10.0"], [Sym("uuid"), ROOT],
           [Sym("paper"), "User", round(PAPER_W + 20, 1), round(max(paper_h, 300.0), 1)],
           [Sym("title_block"), [Sym("title"), "SilentBand v1"], [Sym("rev"), "1"],
            [Sym("comment"), 1, "Generated from hardware/gen/circuit.py - do not edit by hand"]]]
    sch.append([Sym("lib_symbols")] + list(lib.values()))
    for t, x, y in texts:
        sch.append([Sym("text"), t, [Sym("exclude_from_sim"), Sym("no")], [Sym("at"), round(x, 2), round(y, 2), 0],
                    [Sym("effects"), [Sym("font"), [Sym("size"), 2.5, 2.5], [Sym("bold"), Sym("yes")]],
                     [Sym("justify"), Sym("left")]], [Sym("uuid"), uid("text", t)]])

    def place_symbol(lib_id, refdes, value, x, y, fields, pads):
        sym = lib[lib_id]
        x0, y0, x1, y1 = extent(sym)
        s = [Sym("symbol"), [Sym("lib_id"), lib_id], [Sym("at"), x, y, 0], [Sym("unit"), 1],
             [Sym("exclude_from_sim"), Sym("no")], [Sym("in_bom"), Sym("no" if refdes.startswith("#") else "yes")],
             [Sym("on_board"), Sym("no" if refdes.startswith("#") else "yes")], [Sym("dnp"), Sym("no")],
             [Sym("uuid"), uid("sym", refdes)],
             prop("Reference", refdes, x, y + y0 - 1.5), prop("Value", value, x, y + y1 + 1.8)]
        for k, v in fields.items():
            s.append(prop(k, v, x, y, hide=True))
        for q in sexpr.pins(sym):
            s.append([Sym("pin"), q["number"], [Sym("uuid"), uid("pin", refdes, q["number"], q["name"])]])
        s.append([Sym("instances"), [Sym("project"), "silentband",
                                     [Sym("path"), "/" + ROOT, [Sym("reference"), refdes], [Sym("unit"), 1]]]])
        sch.append(s)
        for q in sexpr.pins(sym):
            px, py = round(x + q["x"], 2), round(y - q["y"], 2)
            net = pads.get(q["number"], "")
            if net == "" or net.startswith("NC"):
                ncs.append((px, py, refdes, q["number"]))
                continue
            a = (int(q["angle"]) + 180) % 360
            labels.append((net, px, py, a, refdes, q["number"]))

    for p, x, y in items:
        f = {"Footprint": p.footprint, "Datasheet": "", "LCSC": p.lcsc}
        f.update(p.fields)
        place_symbol(p.symbol, p.ref, p.value, x, y, f, p.pads)
    fx, fy = 15.0, snap(paper_h - 10.0)
    for i, n in enumerate(FLAG_NETS):
        place_symbol("power:PWR_FLAG", f"#FLG{i + 1:02d}", "PWR_FLAG", snap(fx + 25.0 * i + 10), fy, {}, {"1": n})

    for net, x, y, a, r, pin in labels:
        just = "left" if a in (0, 90) else "right"
        sch.append([Sym("global_label"), net, [Sym("shape"), Sym("passive")], [Sym("at"), x, y, a],
                    [Sym("fields_autoplaced"), Sym("yes")], font(justify=just), [Sym("uuid"), uid("gl", r, pin)],
                    [Sym("property"), "Intersheetrefs", "${INTERSHEET_REFS}", [Sym("at"), x, y, 0], font(hide=True)]])
    for x, y, r, pin in ncs:
        sch.append([Sym("no_connect"), [Sym("at"), x, y], [Sym("uuid"), uid("nc", r, pin)]])
    sch.append([Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]])
    sch.append([Sym("embedded_fonts"), Sym("no")])
    os.makedirs(OUT, exist_ok=True)
    with open(SCH, "w") as f:
        f.write(sexpr.dump(sch) + "\n")
    print("saved", SCH, f"{len(items)} symbols, {len(labels)} labels, {len(ncs)} no-connects")


if __name__ == "__main__":
    main()
