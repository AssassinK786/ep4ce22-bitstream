#!/usr/bin/env python3
"""Decode LUT-input mux select codes in LAB-relative coordinates, pooling every LAB and specimen.

Sample = (specimen, LAB, LE n, port) with the source node that drove it (from pips.json).
A relative bit (dframe, dbyte) on the LAB's lane belongs to that mux when its value is the
same for every sample with the same source and is not constant over all sources.
Output: fuzz/lim_codes.json  {"N<n>.<port>": {"bits": [[df,db],...], "codes": {src: "0101.."}}}
"""
import os, sys, re, glob, json, collections
import numpy as np

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN

G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}
RW = {int(k): tuple(v) for k, v in G["row"].items()}
DF = range(-14, 26)    # frames relative to the LAB's LUT base
DB = range(-8, 80)     # bytes below the row's high byte
EDGE = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$")


from rlabel import src_label, relbyte


dirs = sorted(d for d in glob.glob(R + "/work/rt_[0-9]*") if os.path.exists(d + "/pips.json") and not d.endswith("rt_9000"))
if os.environ.get("TRAIN"): dirs = dirs[:int(os.environ["TRAIN"])]
MINS = int(os.environ.get("MINS", "3")); AGREE = float(os.environ.get("AGREE", "0.9"))
OUT = os.environ.get("OUT", R + "/fuzz/lim_codes.json")
samples = collections.defaultdict(list)   # key -> [(src, relbits uint8 array)]
for d in dirs:
    rb = np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)
    win = {}
    for a, b in json.load(open(d + "/pips.json")):
        m = EDGE.match(b)
        if not m:
            continue
        x, y, n, port = int(m[1]), int(m[2]), int(m[3]), m[4]
        if (x, y) not in win:
            hb, lane = RW[y]
            fr = np.array([CB[x] + f for f in DF])
            bl = [relbyte(hb, lane, k) for k in DB]
            by = np.array([b for b, _ in bl]); ln = np.array([l for _, l in bl])
            off = F0 + FLEN * fr[:, None] + by[None, :]
            win[(x, y)] = (rb[off] >> ln[None, :]) & 1
        samples[f"N{n}.{port}"].append((src_label(a, x, y), win[(x, y)]))

out, summary = {}, []
for key in sorted(samples, key=lambda k: (int(k[1:].split(".")[0]), k)):
    S = samples[key]
    srcs = sorted({s for s, _ in S})
    M = np.stack([w for _, w in S])                     # samples x DF x DB
    lab = np.array([srcs.index(s) for s, _ in S])
    cnt = collections.Counter(s for s, _ in S)
    good = [s for s in srcs if cnt[s] >= MINS]
    ok = np.ones(M.shape[1:], bool)
    vals = {}
    for s in good:
        sub = M[lab == srcs.index(s)]
        frac = sub.mean(0)
        maj = (frac >= 0.5).astype(np.uint8)
        ok &= np.maximum(frac, 1 - frac) >= AGREE
        vals[s] = maj
    if not good:
        out[key] = {"bits": [], "codes": {}, "samples": len(S), "sources": len(srcs)}; continue
    first = np.stack([vals[s] for s in good])
    relevant = ok & ~(first == first[0]).all(0)
    idx = np.argwhere(relevant)
    bits = [[DF[i], DB[j]] for i, j in idx]
    codes = {s: "".join(str(int(vals[s][i, j])) for i, j in idx) for s in good}
    out[key] = {"bits": bits, "codes": codes, "samples": len(S), "sources": len(srcs)}
    uniq = len(set(codes.values()))
    summary.append(f"{key:9s} samples {len(S):4d} sources {len(srcs):3d} (>=3: {len(codes):2d}) bits {len(bits):2d} distinct codes {uniq:2d}")
print("\n".join(summary))
json.dump(out, open(OUT, "w"), indent=1)
