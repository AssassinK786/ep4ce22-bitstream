#!/usr/bin/env python3
"""FF / output-select bits per LE slot and LAB-level FF bits, from work/lb_* (fuzz_lab.py).

Per slot n, every specimen is one sample labelled with the LE config (comb / reg / both).
A LAB-relative bit (window as lim_decode.py) belongs to the slot's config when its value is
the same (>= AGREE) within each config class and differs between classes. LAB-level bits:
class = LAB has FFs or not. Output: fuzz/ff_db2.json
"""
import os, sys, glob, json, collections
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import relbyte
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}
RW = {int(k): tuple(v) for k, v in G["row"].items()}
DF, DB = range(-14, 26), range(-8, 80)
AGREE = float(os.environ.get("AGREE", "0.95"))

def window(rb, x, y):
    hb, lane = RW[y]
    fr = np.array([CB[x] + f for f in DF])
    bl = [relbyte(hb, lane, k) for k in DB]
    by = np.array([b for b, _ in bl]); ln = np.array([l for _, l in bl])
    return (rb[F0 + FLEN * fr[:, None] + by[None, :]] >> ln[None, :]) & 1

dirs = sorted(d for d in glob.glob(R + "/work/lb_[0-9]*") if os.path.exists(d + "/top.rbf") and not d.endswith("_9000"))
W, C, DIRS = [], [], []
for d in dirs:
    c = json.load(open(d + "/cfg.json"))
    if c["lab"][0] not in CB or not os.path.exists(d + "/pips.json"):
        continue
    rb = np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)
    W.append(window(rb, *c["lab"])); C.append(c); DIRS.append(d)
W = np.stack(W)
print("specimens", len(W))

def classify(labels):
    """bits consistent within every class (>= AGREE) and not constant across classes."""
    cls = sorted(set(labels)); lab = np.array([cls.index(l) for l in labels])
    ok = np.ones(W.shape[1:], bool); maj = {}
    for i, c in enumerate(cls):
        sub = W[lab == i]
        if len(sub) < 3:
            return None
        frac = sub.mean(0)
        ok &= np.maximum(frac, 1 - frac) >= AGREE
        maj[c] = (frac >= 0.5).astype(np.uint8)
    first = np.stack([maj[c] for c in cls])
    rel = ok & ~(first == first[0]).all(0)
    idx = np.argwhere(rel)
    return {"bits": [[DF[i], DB[j]] for i, j in idx],
            "codes": {c: "".join(str(int(maj[c][i, j])) for i, j in idx) for c in cls},
            "n": {c: int((lab == k).sum()) for k, c in enumerate(cls)}}

import re
def outs(d, x, y):
    """per LE n: {'local': 'comb'|'reg', 'buf': ..., 'ff': True} from the STA hops."""
    o = collections.defaultdict(dict)
    for a, b in json.load(open(d + "/pips.json")):
        m = re.match(r"(FF|LCCOMB)_X(\d+)_Y(\d+)_N(\d+)$", a)
        if not m or (int(m[2]), int(m[3])) != (x, y):
            continue
        n = int(m[4]) - (1 if m[1] == "FF" else 0)
        src = "reg" if m[1] == "FF" else "comb"
        if m[1] == "FF":
            o[n]["ff"] = True
        if b.startswith("LOCAL_LINE"):
            o[n]["local"] = src
        elif b.startswith("LE_BUFFER"):
            o[n]["buf"] = src
    return o
O = [outs(d, *c["lab"]) for d, c in zip(DIRS, C)]

def classify_sub(labels):
    keep = [i for i, l in enumerate(labels) if l is not None]
    global W
    Wall = W
    W = Wall[keep]
    try:
        return classify([labels[i] for i in keep])
    finally:
        W = Wall

out = {"coords": "(dframe from the column's LUT base, LAB-relative row byte via rlabel.relbyte), lane = row lane",
       "le": {}, "lab": None}
for n in range(0, 32, 2):
    e = {}
    for key in ("local", "buf"):
        e[key + "_sel"] = classify_sub([O[i][n].get(key) for i in range(len(C))])
    e["ff_used"] = classify_sub(["ff" if (C[i]["cfg"][str(n)] != "comb") else "noff" for i in range(len(C))])
    out["le"][f"N{n}"] = e
    print(f"N{n:<2}", {k: (None if v is None else (v["bits"], v["codes"], v["n"])) for k, v in e.items()})
r = classify(["noff" if c["nofl"] else "ff" for c in C])
out["lab"] = r
print("LAB", None if r is None else (len(r["bits"]), r["bits"][:12], r["codes"], r["n"]))
json.dump(out, open(R + "/fuzz/ff_db2.json", "w"), indent=1)
