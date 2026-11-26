#!/usr/bin/env python3
"""Hold-out check: solve on all but the last H specimens, predict the bits of the last H from their tags."""
import os, sys, glob, json, subprocess, collections
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = int(os.environ.get("H", "50"))
dirs = sorted(d for d in glob.glob(R + "/work/rt_[0-9]*") if os.path.exists(d + "/pips.json") and not d.endswith("rt_9000"))
train, test = dirs[:-H], dirs[-H:]
subprocess.run([sys.executable, R + "/tools/route_solve.py"] + train, check=True, stdout=subprocess.DEVNULL)
model = json.load(open(R + "/fuzz/route_pips.json"))
sys.path.insert(0, R + "/tools"); from rbf import F0, FLEN
def tagset(d):
    s = {f"{a}->{b}" for a, b in json.load(open(d + "/pips.json"))}
    s |= {f"SITE:{x}_{y}_{n}" for x, y, n in json.load(open(d + "/sites.json"))}
    return s
stats = collections.Counter()
by_size = collections.defaultdict(collections.Counter)
for d in test:
    rb = open(d + "/top.rbf", "rb").read(); ts = tagset(d)
    for loc, e in model.items():
        f, o, b = map(int, loc.split(":"))
        actual = (rb[F0 + FLEN * f + o] >> b) & 1
        pred = int(any(t in ts for t in e["tags"])) ^ int(e["inverted"])
        size = min(len(e["tags"]), 9)
        ok = pred == actual
        stats["ok" if ok else "bad"] += 1
        by_size[size]["ok" if ok else "bad"] += 1
print("held-out specimens", len(test), "bit predictions", sum(stats.values()), "accuracy %.4f" % (stats["ok"] / sum(stats.values())))
for s in sorted(by_size):
    c = by_size[s]; print(f"  cover size {s}{'+' if s == 9 else ' '}: {c['ok'] / (c['ok'] + c['bad']):.4f}  ({c['bad']} wrong of {c['ok'] + c['bad']})")
