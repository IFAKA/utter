"""Neckband electrode layout (after SilentWear, arXiv 2603.02847): where EL1-16 sit and which bipolar pairs
the software derives from them.

The board records every electrode against REF (monopolar), so any pair is a subtraction. SilentWear's
band uses 15 front electrodes in 3 rows (10 vertical bipolar channels over the infrahyoid muscles) and
2 bipolar pairs per side over the sternocleidomastoid (SCM), ground at the back of the neck. With 16
inputs we keep both muscle groups: a 3 x 4 front grid plus 2 electrodes per SCM.

Positions are cm, x from the midline (+ = user's left), y from the band's top edge (just below the
larynx/thyroid notch, so swallowing moves under the band rather than across its edge). REF and RLD sit
at the back of the neck (C7), where SilentWear puts its shorted ground electrodes.
"""
from __future__ import annotations

# EL number -> (site, x cm, y cm)
SITES = {
    1: ("front top, right outer", -3.0, 0.0), 2: ("front top, right inner", -1.0, 0.0),
    3: ("front top, left inner", 1.0, 0.0), 4: ("front top, left outer", 3.0, 0.0),
    5: ("front mid, right outer", -3.0, 2.0), 6: ("front mid, right inner", -1.0, 2.0),
    7: ("front mid, left inner", 1.0, 2.0), 8: ("front mid, left outer", 3.0, 2.0),
    9: ("front low, right outer", -3.0, 4.0), 10: ("front low, right inner", -1.0, 4.0),
    11: ("front low, left inner", 1.0, 4.0), 12: ("front low, left outer", 3.0, 4.0),
    13: ("right SCM, upper", -6.5, 0.5), 14: ("right SCM, lower", -6.0, 3.5),
    15: ("left SCM, upper", 6.5, 0.5), 16: ("left SCM, lower", 6.0, 3.5),
}
REF_RLD = "back of the neck at C7, side by side (REF = J1 pin 17, RLD = pin 19)"

_COLUMNS = [(1, 5, 9), (2, 6, 10), (3, 7, 11), (4, 8, 12)]
# 0-based channel pairs for dsp.features: 8 vertical (along the strap muscles, as SilentWear), the 2 SCM
# pairs, and 3 across the midline (left vs right side of the larynx).
PAIRS = ([(a - 1, b - 1) for col in _COLUMNS for a, b in zip(col, col[1:])]
         + [(12, 13), (14, 15)]
         + [(1, 2), (5, 6), (9, 10)])


def describe() -> str:
    rows = [f"EL{n:<2d} {s:24s} x {x:+5.1f} cm  y {y:4.1f} cm" for n, (s, x, y) in SITES.items()]
    return "\n".join(rows + [f"REF/RLD {REF_RLD}"])
