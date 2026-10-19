"""Release gate: DRC clean, ERC clean (except documented waivers), circuit == schematic == PCB nets.

Run with KiCad's Python (build.sh does).  Exit code 1 on any failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
import circuit  # noqa: E402
import sexpr  # noqa: E402

OUT = os.path.join(circuit.REPO, "hardware/out")
CLI = os.path.join(sexpr.KICAD, "Contents/MacOS/kicad-cli")
PCB, SCH = os.path.join(OUT, "silentband.kicad_pcb"), os.path.join(OUT, "silentband.kicad_sch")
FOOTPRINT_ONLY = {("SW3", "SH"), ("J4", "MP")}  # mechanical GND pads with no symbol pin
# ERC waivers (reviewed): both ADS DOUT on MISO (tri-state while CS high); unused ADS GPIO1-4 tied to GND
# (GPIO register = inputs); TESTP/TESTN tied to AVDD per datasheet.
WAIVE = [("DOUT", "DOUT"), ("GPIO", "#FLG"), ("TESTP", "U7 Pin 5")]
IGNORE_ERC = {"lib_symbol_issues", "footprint_link_issues"}  # no global lib tables in the CLI env


def run(*args):
    subprocess.run([CLI, *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    fails = []
    drc = os.path.join(OUT, "drc.json")
    run("pcb", "drc", "--refill-zones", "--format", "json", "--severity-error", "-o", drc, PCB)
    d = json.load(open(drc))
    if d["violations"] or d["unconnected_items"]:
        fails.append(f"DRC: {len(d['violations'])} errors, {len(d['unconnected_items'])} unconnected")
    erc = os.path.join(OUT, "erc.json")
    run("sch", "erc", "--format", "json", "-o", erc, SCH)
    waived = 0
    for s in json.load(open(erc))["sheets"]:
        for v in s["violations"]:
            if v["type"] in IGNORE_ERC:
                continue
            text = " | ".join(i["description"] for i in v["items"])
            if v["type"] == "pin_to_pin" and any(a in text and b in text for a, b in WAIVE):
                waived += 1
                continue
            fails.append(f"ERC {v['severity']}: {v['description']} [{text}]")

    with tempfile.TemporaryDirectory() as tmp:
        netf = os.path.join(tmp, "sb.net")
        run("sch", "export", "netlist", "--format", "kicadsexpr", "-o", netf, SCH)
        net = sexpr.parse(open(netf).read())
    sch = {}
    for n in sexpr.find(sexpr.first(net, "nets"), "net"):
        name = sexpr.first(n, "name")[1].lstrip("/")
        for nd in sexpr.find(n, "node"):
            r = sexpr.first(nd, "ref")[1]
            if not r.startswith("#") and not name.startswith("unconnected"):
                sch[(r, sexpr.first(nd, "pin")[1])] = name
    cir = {(p.ref, pad): n for p in circuit.build() for pad, n in p.pads.items() if n and not n.startswith("NC")}
    pcb = {}
    for fp in pcbnew.LoadBoard(PCB).GetFootprints():
        for pd in fp.Pads():
            if pd.GetNetname() and not pd.GetNetname().startswith("NC"):
                pcb[(fp.GetReference(), pd.GetNumber())] = pd.GetNetname()
    for name, other in (("schematic", sch), ("PCB", pcb)):
        bad = [(k, cir.get(k), other.get(k)) for k in set(cir) | set(other)
               if cir.get(k) != other.get(k) and not (name == "schematic" and k in FOOTPRINT_ONLY)]
        if bad:
            fails.append(f"circuit vs {name}: {len(bad)} pad/net mismatches, e.g. {sorted(bad)[:5]}")
    for f in fails:
        print("FAIL", f)
    if not fails:
        print(f"check OK: DRC 0 errors / 0 unconnected; ERC clean ({waived} waived pin-type warnings); "
              f"circuit == schematic == PCB ({len(cir)} pad connections)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
