"""Relative source labels for routing nodes."""
import re


def src_label(node, x, y):
    """Source name relative to the destination LAB."""
    m = re.match(r"^(\w+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?(?:\.(\w+))?$", node)
    if not m:
        return node
    kind, sx, sy, sn, si, port = m.groups()
    same = int(sx) == x and int(sy) == y
    tag = kind if same else f"{kind}@{int(sx)-x},{int(sy)-y}"
    if si is not None:
        tag += f"_I{si}"
    if kind in ("FF", "LCCOMB", "LOCAL_LINE"):
        tag += f"_N{sn}"
    return tag


def relbyte(hb, lane, db):
    """Absolute (frame byte, bit) of LAB-relative byte db for a row with high byte hb on bit lane.
    Rows run downward through frame bytes 295..1 and continue on the next lane when they pass byte 1."""
    import os
    period, dl = WRAP
    b = hb - db
    while b < LO:
        b += period
        lane += dl
    while b >= LO + period:
        b -= period
        lane -= dl
    return b, lane


import os as _os
WRAP = tuple(int(v) for v in _os.environ.get("WRAP", "294,1").split(","))
LO = int(_os.environ.get("WRAPLO", "2"))
