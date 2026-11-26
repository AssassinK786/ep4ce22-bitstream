#!/usr/bin/env python3
"""Clock chain from R8, from work/ck_* / nc_* pairs (fuzz_clk.py).

D_L = ck_L ^ nc_L for each LAB L (CRAM bits; values from ck_L).
  chain  : positions in every D_L with the same value (pin R8 -> CLKCTRL -> global clock)
  lab    : LAB-relative positions in every D_L's LAB window, same value, excluding LUT-content
           and LUT-input-mux positions (LAB clock select, FF clock enable ...)
  region : per LAB, what is left (row / spine enables), as a per-LAB table
Output: fuzz/clock.json {"chain": [entries], "lab": [[df, db, dlane, value]], "region": {"x,y": [entries]}}
"""
import os, sys, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES
from rlabel import relbyte
from fuzz_clk import LABS
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}
EXREL = {(SLOT[k][0], LEOFF[n] + ((1 - SLOT[k][1]) if (n // 2) % 2 else SLOT[k][1])) for n in LEOFF for k in SLOT}
EXREL |= {(df, db) for e in LIM.values() for df, db in e["bits"]}
lin = lambda b, l: l * 294 + (295 - b)


def diff(a, b):
    out = {}
    for f in range(NFRAMES):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            x = a[o + byte] ^ b[o + byte]
            for bit in range(8):
                if x >> bit & 1:
                    out[(f, byte, bit)] = (a[o + byte] >> bit) & 1
    return out


def rel(x, y, p):
    f, byte, bit = p
    hb, lane = RW[y]
    df = f - CB[x]
    db = lin(byte, bit) - lin(hb, lane)
    return (df, db) if -14 <= df <= 25 and -8 <= db <= 80 else None


D = {}
for x, y in LABS:
    a, b = f"{R}/work/ck_{x}_{y}/top.rbf", f"{R}/work/nc_{x}_{y}/top.rbf"
    if os.path.exists(a) and os.path.exists(b):
        D[(x, y)] = diff(open(a, "rb").read(), open(b, "rb").read())
print("pairs", len(D), {k: len(v) for k, v in D.items()})
keys = list(D)
chain = {p: v for p, v in D[keys[0]].items() if all(p in D[k] and D[k][p] == v for k in keys)}
labrel = None
for (x, y), dd in D.items():
    s = {}
    for p, v in dd.items():
        r = rel(x, y, p)
        if r and r not in EXREL and p not in chain:
            s[r] = (v, p[2] - RW[y][1])
    labrel = s if labrel is None else {r: t for r, t in labrel.items() if r in s and s[r] == t}
region = {}
for (x, y), dd in D.items():
    rest = []
    for p, v in dd.items():
        if p in chain:
            continue
        r = rel(x, y, p)
        if r and (r in labrel or r in EXREL):
            continue
        rest.append(["cram", *p, v])
    region[f"{x},{y}"] = sorted(rest)
print("chain bits", len(chain), " LAB-relative clock bits", len(labrel), sorted(labrel.items()))
print("left per LAB:", {k: len(v) for k, v in region.items()})
json.dump({"chain": [["cram", *p, v] for p, v in sorted(chain.items())],
           "lab": [[df, db, dl, v] for (df, db), (v, dl) in sorted(labrel.items())],
           "region": region}, open(R + "/fuzz/clock.json", "w"), indent=0)
