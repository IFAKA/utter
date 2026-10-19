#!/bin/sh
# Regenerate the Utter board end to end: PCB (placement + FreeRouting), schematic, checks, fab outputs.
#   ./build.sh [--no-route] [--reuse-route] [-q]
set -eo pipefail
cd "$(dirname "$0")"
KICAD_APP="${KICAD_APP:-$HOME/Applications/KiCad/KiCad.app}"
KPY="$KICAD_APP/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
export KICAD_APP
"$KPY" gen_pcb.py "$@" 2>&1 | grep -v -e '^WARNING' -e 'stdpbase.cpp'
"$KPY" gen_sch.py
"$KPY" check.py
"$KPY" gen_fab.py
