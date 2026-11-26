#!/usr/bin/env python3
"""Explain LAB-window bits by single binary features of the LAB (from the complete STA hops):
LE_BUFFER_I<m> driven, LOCAL_INTERCONNECT_I<k> used, LOCAL_LINE_I<k> used, BLK_CLK_LIM_I<k> used,
FF at N<n> present. A feature explains a bit when bit == feature (or its inverse) in >= AGREE of
the samples and the feature is on in >= 3 % and off in >= 3 %. Output: fuzz/feat_bits.json"""
import os, sys, re, glob, json, collections
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
exec(open(R + "/tools/li_joint.py").read().split("W = np.stack(S_win)")[0].split('dirs = sorted(')[0])
AG = float(os.environ.get("AGREE", "0.98"))
dirs = sorted(d for pat in ("rt_[0-9]*", "lb_[0-9]*") for d in glob.glob(R + "/work/" + pat)
              if os.path.exists(d + "/pips.json") and not d.endswith("_9000"))
F, Wl = [], []
for d in dirs:
    feats = collections.defaultdict(set); labs = set()
    for a, b in json.load(open(d + "/pips.json")):
        for node in (a, b):
            m = re.match(r"(LE_BUFFER|LOCAL_INTERCONNECT|LOCAL_LINE|BLK_CLK_LIM|BLK_CLK_BUF|LAB_CLK)_X(\d+)_Y(\d+)_N0_I(\d+)", node)
            if m:
                feats[(int(m[2]), int(m[3]))].add(f"{m[1]}_I{m[4]}")
            m = re.match(r"FF_X(\d+)_Y(\d+)_N(\d+)", node)
            if m:
                feats[(int(m[1]), int(m[2]))].add(f"FF_N{m[3]}")
        m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N", b)
        if m:
            labs.add((int(m[1]), int(m[2])))
    rb = np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)
    for lab in labs:
        if lab[0] in CB:
            F.append(feats[lab]); Wl.append(window(rb, *lab))
W = np.stack(Wl); N = len(W)
names = sorted(set().union(*F))
X = np.array([[n in f for n in names] for f in F])
on = X.mean(0); keep = (on >= 0.03) & (on <= 0.97)
names = [n for n, k in zip(names, keep) if k]; X = X[:, keep]
print("samples", N, "features", len(names))
var = ~(W == W[0]).all(0)
out = {}
for i, j in np.argwhere(var):
    if (DF[i], DB[j]) in known:
        continue
    b = W[:, i, j].astype(bool)
    agree = (X == b[:, None]).mean(0)
    k = int(np.argmax(np.maximum(agree, 1 - agree)))
    a = agree[k]
    if max(a, 1 - a) >= AG:
        out[f"{DF[i]},{DB[j]}"] = {"feature": names[k], "inverted": bool(a < 0.5), "agree": round(float(max(a, 1 - a)), 4)}
print("explained", len(out))
byf = collections.defaultdict(list)
for k, v in out.items():
    byf[v["feature"] + ("~" if v["inverted"] else "")].append(k)
for f, ks in sorted(byf.items(), key=lambda t: -len(t[1]))[:40]:
    print(f"  {f:28s} {ks}")
json.dump(out, open(R + "/fuzz/feat_bits.json", "w"), indent=0)
