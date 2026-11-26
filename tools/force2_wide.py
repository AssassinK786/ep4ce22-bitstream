#!/usr/bin/env python3
"""Re-derive force2 codes with a wide window (frames -25..25, row bytes -12..82) from the stored builds.
Element-plane frames (-1, 8, 9, 11) and the dest LUT / LUT-input-mux positions are excluded as before.
Writes fuzz/force2w_<x>_<y>.json in the force2 format."""
import os, sys, re, glob, json
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import relbyte
sys.argv = [sys.argv[0], "0", "0"]
from force_probe import excl, CB, RW
for fj in glob.glob(R + "/fuzz/force2_[0-9]*_[0-9]*.json"):
    x, y = map(int, os.path.basename(fj)[7:-5].split("_"))
    out = []
    for r in json.load(open(fj)):
        dy, m, k = r["pair"]
        if not r.get("legal"):
            out.append(r); continue
        n = m - m % 2; d = 2 if (dy == 0 and n == 0) else 0
        dX = f"{R}/work/f2_{x}_{y}_{x}_{y + dy}_{n}_d{d}_X/top.rbf"
        dF = f"{R}/work/f2_{x}_{y}_{dy}_{m}_{k}_F/top.rbf"
        a, b = open(dX, "rb").read(), open(dF, "rb").read()
        hb, lane = RW[y]; ex = excl(d); bits = []
        for df in range(-25, 26):
            for db in range(-12, 83):
                byte, ln = relbyte(hb, lane, db)
                o = F0 + FLEN * (CB[x] + df) + byte
                if (a[o] ^ b[o]) >> ln & 1 and (df, db) not in ex and df not in (-1, 8, 9, 11):
                    bits.append([df, db, (b[o] >> ln) & 1])
        out.append({**r, "bits": bits})
    json.dump(out, open(R + f"/fuzz/force2w_{x}_{y}.json", "w"), indent=0)
    print(x, y, sum(1 for r in out if r.get("legal")))
