#!/usr/bin/env python3
"""Solve sparse routing specimens (route_sparse.py) in coordinates relative to each hop's
destination node.

1. Background: per bit, the majority value over all specimens; a specimen's "active" bits are
   the ones that differ from it.
2. Every hop (a -> b) is labelled relative to b's (X, Y): e.g. "R4@+1,0_I19 -> LOCAL_INTERCONNECT_I2".
3. For each label, the active bits in a window around b's tile are taken in tile-relative
   coordinates (dframe from the column base, row-linear byte offset); bits present in >= AGREE of
   the label's occurrences, and rare elsewhere (< BASE), are its bits.
Output: fuzz/sparse_pips.json
"""
import os, sys, re, glob, json, collections
import numpy as np

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES, SIZE

G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}
RW = {int(k): tuple(v) for k, v in G["row"].items()}
AGREE = float(os.environ.get("AGREE", "0.9"))
BASE = float(os.environ.get("BASE", "0.05"))
MINOCC = int(os.environ.get("MINOCC", "3"))
WF, WB = 45, 160                      # window: frames +-WF, row-linear bytes +-WB
NODE = re.compile(r"^(\w+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?(?:\.(\S+))?$")


def node_xy(n):
    m = NODE.match(n)
    return (int(m[2]), int(m[3])) if m else None


def label(a, b):
    mb, ma = NODE.match(b), NODE.match(a)
    if not mb:
        return None
    x, y = int(mb[2]), int(mb[3])
    def rel(m, base):
        if not m:
            return a
        kind, sx, sy, sn, si, port = m.groups()
        t = kind if (int(sx), int(sy)) == base else f"{kind}@{int(sx)-base[0]:+d},{int(sy)-base[1]:+d}"
        if kind in ("LCCOMB", "FF", "LOCAL_LINE") or kind.startswith("BLK_CLK"):
            t += f"_N{sn}"
        if si is not None:
            t += f"_I{si}"
        if port:
            t += "." + port
        return t
    return f"{rel(ma, (x, y))} -> {rel(mb, (x, y))}", (x, y)


def rowpos(byte, lane):
    return lane * 294 + (295 - byte)


dirs = sorted(d for d in glob.glob(R + "/work/sp_[0-9]*") if os.path.exists(d + "/pips.json"))
n = len(dirs)
print("specimens", n)
mask = np.zeros(SIZE, bool)
for f in range(NFRAMES):
    o = F0 + FLEN * f
    mask[o + 2:o + 296] = True                 # bytes 2..295 (byte 1 kept out, as in relbyte)
idx = np.nonzero(mask)[0]
cnt = np.zeros(len(idx) * 8, np.uint16)
raw = []
for d in dirs:
    v = np.unpackbits(np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)[idx], bitorder="little")
    cnt += v
    raw.append(np.packbits(v))
mode = cnt > n // 2
active = []
for p in raw:
    v = np.unpackbits(p).astype(bool) ^ mode
    k = np.nonzero(v)[0]
    byte = idx[k // 8]
    fr, off = divmod(byte - F0, FLEN)
    active.append((fr, off, (k % 8)))
del raw
print("mean active bits per specimen", np.mean([len(a[0]) for a in active]).round(1))


def window(i, x, y):
    if x not in CB or y not in RW:
        return None
    fr, off, lane = active[i]
    hb, ln = RW[y]
    df = fr - CB[x]
    db = rowpos(off, lane) - rowpos(hb, ln)
    sel = (np.abs(df) <= WF) & (np.abs(db) <= WB)
    return set(zip(df[sel].tolist(), db[sel].tolist()))


occ = collections.defaultdict(list)      # label -> [set of rel bits]
allwin = collections.Counter()
nwin = 0
for i, d in enumerate(dirs):
    for a, b in json.load(open(d + "/pips.json")):
        lb = label(a, b)
        if not lb:
            continue
        key, (x, y) = lb
        w = window(i, x, y)
        if w is None:
            continue
        occ[key].append(w)
        allwin.update(w)
        nwin += 1

out = {}
kinds = collections.Counter()
for key, ws in occ.items():
    if len(ws) < MINOCC:
        continue
    c = collections.Counter()
    for w in ws:
        c.update(w)
    bits = sorted(b for b, k in c.items() if k >= AGREE * len(ws) and allwin[b] / nwin < BASE)
    out[key] = {"n": len(ws), "bits": bits}
    kinds[(re.sub(r"@[-+\d,]+|_I\d+|_N\d+", "", key), len(bits) > 0)] += 1
print("labels with >=", MINOCC, "occurrences:", len(out))
for (k, ok), c in sorted(kinds.items(), key=lambda t: -t[1])[:30]:
    print(f"  {c:4d} {'with bits' if ok else 'NO bits  '}  {k}")
json.dump(out, open(R + "/fuzz/sparse_pips.json", "w"), indent=0)
