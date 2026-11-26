#!/usr/bin/env python3
"""Add LOCAL_LINE (LE feedback) source codes to fuzz/lim_codes.json, using its existing
bit positions per LUT input; samples from work/rt_* and work/lb_*. Needs >= MINS samples
with >= AGREE agreement per bit. Output: fuzz/lim_codes_ll.json"""
import os, sys, re, glob, json, collections
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import src_label, relbyte
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
L = json.load(open(R + "/fuzz/lim_codes.json"))
MINS, AGREE = int(os.environ.get("MINS", "2")), float(os.environ.get("AGREE", "0.9"))
EDGE = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$")
obs = collections.defaultdict(list)
for d in sorted(glob.glob(R + "/work/rt_[0-9]*") + glob.glob(R + "/work/lb_[0-9]*")):
    if not os.path.exists(d + "/pips.json") or d.endswith("_9000"):
        continue
    rb = None
    for a, b in json.load(open(d + "/pips.json")):
        m = EDGE.match(b)
        if not m or not a.startswith("LOCAL_LINE"):
            continue
        x, y, n, port = int(m[1]), int(m[2]), int(m[3]), m[4]
        key = f"N{n}.{port}"
        if key not in L or not L[key]["bits"] or x not in CB:
            continue
        rb = rb if rb is not None else open(d + "/top.rbf", "rb").read()
        hb, lane = RW[y]
        code = ""
        for df, db in L[key]["bits"]:
            byte, ln = relbyte(hb, lane, db)
            code += str((rb[F0 + FLEN * (CB[x] + df) + byte] >> ln) & 1)
        obs[(key, src_label(a, x, y))].append(code)
added = rejected = 0
for (key, src), codes in obs.items():
    if src in L[key]["codes"] or len(codes) < MINS:
        continue
    cols = list(zip(*codes))
    maj = "".join(max(set(c), key=c.count) for c in cols)
    if min(c.count(v) / len(c) for c, v in zip(cols, maj)) >= AGREE and maj not in L[key]["codes"].values():
        L[key]["codes"][src] = maj; added += 1
    else:
        rejected += 1
print("LOCAL_LINE codes added", added, "rejected", rejected)
json.dump(L, open(R + "/fuzz/lim_codes_ll.json", "w"), indent=1)
