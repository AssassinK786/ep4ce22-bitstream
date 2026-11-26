#!/usr/bin/env python3
"""Per-pin I/O bits and the A15 output path, from work/pn_* (fuzz_pins.py).

For pin k: DA = allA ^ minusA_k, DB = allB ^ minusB_k (CRAM bits and periphery logical bytes).
I/O bits of k = positions in both DA and DB with the same value in allA and allB.
The A15 path (driver at LAB (38,31) N2 in set A) = DA - I/O bits, minus LUT-content and
LUT-input-mux positions of that LAB, i.e. the LE output side + routing to the pad.
Output: fuzz/pins.json {pin: {"out"|"in": [entries]}}, fuzz/paths.json {"A15_from_38_31_N2": [entries]}
entry: ["cram", frame, byte, bit, value] or ["periph", logical_byte, value]
"""
import os, sys, json
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES, PERIPH, PERIPH_LEN
from rlabel import relbyte
OUTS = ["A15", "A13", "B13", "A11", "D1", "F3", "B1", "L3"]
INS = ["J15", "E1", "M1", "T8", "B9", "M15"]
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}


def load(tag):
    p = f"{R}/work/pn_{tag}/top.rbf"
    return open(p, "rb").read() if os.path.exists(p) else None


def diff(a, b):
    cram = {}
    for f in range(NFRAMES):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            x = a[o + byte] ^ b[o + byte]
            for bit in range(8):
                if x >> bit & 1:
                    cram[(f, byte, bit)] = (a[o + byte] >> bit) & 1
    per = {i: a[PERIPH + 4 * i] for i in range(PERIPH_LEN // 4) if a[PERIPH + 4 * i] != b[PERIPH + 4 * i]}
    return cram, per


allA, allB = load("allA"), load("allB")
pins, paths = {}, {}
for p in OUTS + INS:
    mA, mB = load(f"minusA_{p}"), load(f"minusB_{p}")
    if not (mA and mB and allA and allB):
        print(p, "missing builds"); continue
    cA, pA = diff(allA, mA)
    cB, pB = diff(allB, mB)
    io_c = {k: v for k, v in cA.items() if k in cB and cB[k] == v}
    io_p = {k: v for k, v in pA.items() if k in pB and pB[k] == v}
    use = "out" if p in OUTS else "in"
    pins[p] = {use: [["cram", *k, v] for k, v in sorted(io_c.items())] + [["periph", k, v] for k, v in sorted(io_p.items())]}
    print(f"{p:4s} {use:3s} I/O cram bits {len(io_c):3d} periph bytes {len(io_p):2d}  (A-only {len(cA) - len(io_c)}, B-only {len(cB) - len(io_c)})")
    if p == "A15":
        x, y = 38, 31
        hb, lane = RW[y]
        excl = set()
        for n in LEOFF:
            for k in SLOT:
                df, db = SLOT[k]
                db = (1 - db) if (n // 2) % 2 else db
                excl.add((CB[x] + df, *relbyte(hb, lane, LEOFF[n] + db)))
        for e in LIM.values():
            for df, db in e["bits"]:
                excl.add((CB[x] + df, *relbyte(hb, lane, db)))
        route = {k: v for k, v in cA.items() if k not in io_c and k not in excl}
        paths["A15_from_38_31_N2"] = [["cram", *k, v] for k, v in sorted(route.items())]
        print("     A15 path bits (LE output side + routing):", len(route))
json.dump(pins, open(R + "/fuzz/pins.json", "w"), indent=0)
json.dump(paths, open(R + "/fuzz/paths.json", "w"), indent=0)
