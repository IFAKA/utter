"""Fab outputs for JLCPCB: gerbers + drill (zip), BOM and CPL (JLC column names), schematic PDF, 3D renders.

Run with any Python 3.9+ after gen_pcb.py / gen_sch.py (build.sh does).
Output: hardware/out/fab/
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
import circuit  # noqa: E402
import sexpr  # noqa: E402

OUT = os.path.join(circuit.REPO, "hardware/out")
FAB = os.path.join(OUT, "fab")
CLI = os.path.join(sexpr.KICAD, "Contents/MacOS/kicad-cli")
PCB, SCH = os.path.join(OUT, "utter.kicad_pcb"), os.path.join(OUT, "utter.kicad_sch")
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.Paste,F.Silkscreen,B.Silkscreen,Edge.Cuts"


def cli(*args):
    subprocess.run([CLI, *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    shutil.rmtree(FAB, ignore_errors=True)
    gdir = os.path.join(FAB, "gerbers")
    os.makedirs(gdir)
    cli("pcb", "export", "gerbers", "--layers", LAYERS, "--no-x2", "--subtract-soldermask", "-o", gdir + "/", PCB)
    cli("pcb", "export", "drill", "--format", "excellon", "--drill-origin", "absolute", "--excellon-units", "mm",
        "-o", gdir + "/", PCB)
    zpath = os.path.join(FAB, "utter-gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)

    # CPL: KiCad position file -> JLC columns
    pos = os.path.join(FAB, "pos.csv")
    cli("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "-o", pos, PCB)
    parts = {p.ref: p for p in circuit.build()}
    rows = list(csv.DictReader(open(pos)))
    os.remove(pos)
    with open(os.path.join(FAB, "utter-cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in rows:
            if r["Ref"] in parts and not parts[r["Ref"]].dnp:
                w.writerow([r["Ref"], r["PosX"] + "mm", r["PosY"] + "mm",
                            "Top" if r["Side"] == "top" else "Bottom", r["Rot"]])
    placed = {r["Ref"] for r in rows}
    missing = set(parts) - placed
    if missing:
        raise SystemExit(f"CPL missing {sorted(missing)}")

    # BOM grouped by (value, footprint, LCSC)
    groups: dict = {}
    for p in parts.values():
        if not p.dnp:
            groups.setdefault((p.value, p.footprint.split(":")[1], p.lcsc), []).append(p.ref)
    key = lambda r: (r.rstrip("0123456789"), int(r[len(r.rstrip("0123456789")):]))
    with open(os.path.join(FAB, "utter-bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Quantity"])
        for (val, fp, lcsc), refs in sorted(groups.items(), key=lambda kv: key(sorted(kv[1], key=key)[0])):
            w.writerow([val, ",".join(sorted(refs, key=key)), fp, lcsc, len(refs)])

    cli("sch", "export", "pdf", "-o", os.path.join(FAB, "utter-schematic.pdf"), SCH)
    for side in ("top", "bottom"):
        try:
            cli("pcb", "render", "--side", side, "--quality", "high", "--width", "1600", "--height", "1100",
                "--background", "opaque", "-o", os.path.join(FAB, f"render-{side}.png"), PCB)
        except subprocess.CalledProcessError:
            print(f"warning: 3D render ({side}) failed")
    cli("pcb", "export", "pdf", "--layers", "F.Cu,F.Silkscreen,Edge.Cuts", "--mode-single",
        "-o", os.path.join(FAB, "utter-top-assembly.pdf"), PCB)
    print("fab outputs in", FAB, f"({len(groups)} BOM lines, {len(rows)} placements)")


if __name__ == "__main__":
    main()
