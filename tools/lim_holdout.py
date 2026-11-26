#!/usr/bin/env python3
"""Hold-out check for lim_codes: decode on first TRAIN specimens, test used LUT inputs of the rest."""
import os, sys, re, glob, json, collections, subprocess
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
import importlib.util
spec = importlib.util.spec_from_file_location("ld", R + "/tools/lim_decode.py")
TRAIN = int(os.environ.get("TRAIN", "150"))
tmp = R + "/fuzz/_lim_train.json"
subprocess.run([sys.executable, R + "/tools/lim_decode.py"], env=dict(os.environ, TRAIN=str(TRAIN), OUT=tmp), check=True, stdout=subprocess.DEVNULL)
model = json.load(open(tmp))
from rbf import F0, FLEN
G = json.load(open(R + "/fuzz/lab_grid.json")); CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
from rlabel import src_label, relbyte
EDGE = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$")
dirs = sorted(d for d in glob.glob(R + "/work/rt_[0-9]*") if os.path.exists(d + "/pips.json") and not d.endswith("rt_9000"))[TRAIN:]
st = collections.Counter(); fails = collections.Counter(); unseen = collections.Counter()
for d in dirs:
    rb = open(d + "/top.rbf", "rb").read()
    for a, b in json.load(open(d + "/pips.json")):
        m = EDGE.match(b)
        if not m: continue
        x, y, n, port = int(m[1]), int(m[2]), int(m[3]), m[4]
        e = model[f"N{n}.{port}"]; s = src_label(a, x, y)
        if not e["bits"]:
            st["nomodel"] += 1; continue
        if s not in e["codes"]:
            unseen[s] += 1; st["unseen"] += 1; continue
        hb, lane = RW[y]
        got = "".join(str((rb[F0 + FLEN * (CB[x] + df) + relbyte(hb, lane, db)[0]] >> relbyte(hb, lane, db)[1]) & 1) for df, db in e["bits"])
        # decode: which source code matches?
        cands = [k for k, v in e["codes"].items() if v == got]
        if got == e["codes"][s]: st["ok"] += 1
        else: st["bad"] += 1; fails[(f"N{n}.{port}", s, tuple(cands))] += 1
tot = st["ok"] + st["bad"]
print(f"held-out {len(dirs)} specimens: {st['ok']}/{tot} exact = {st['ok']/tot:.4f}; unseen-source samples {st['unseen']}; inputs with no decoded mux {st['nomodel']}")
for k, c in fails.most_common(10): print("  fail", c, k)
for k, c in unseen.most_common(8): print("  unseen", c, k)
