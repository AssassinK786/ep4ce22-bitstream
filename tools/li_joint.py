#!/usr/bin/env python3
"""Joint decode of LAB local-line (LOCAL_INTERCONNECT I0..I37) driver muxes, LAB-relative.

Sample = (specimen, LAB): the source of every local line of that LAB ('-' = unused; complete
because every reported net appears on a reg->reg path) and the LAB window bits.
For every window bit that varies and is not a known LUT / LUT-input-mux position, find the
smallest set of lines (one line, else a pair) whose sources determine it:
  score = fraction of samples in groups (by source tuple) of size >= MING that agree with the
  group majority; a line set explains the bit when score >= AGREE and coverage >= MINCOV.
Output: fuzz/li_joint.json {bit "df,db": {"lines": [k...], "table": {"src|src": v}, "score": s}}
TRAIN=<n> / HOLDOUT=1 as in mux_decode.py.
"""
import os, sys, re, glob, json, itertools, collections
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import src_label, relbyte
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}
DF, DB = range(*map(int, os.environ.get("DFR", "-25,26").split(","))), range(-8, 80)
MING, AGREE, MINCOV = int(os.environ.get("MING", "3")), float(os.environ.get("AGREE", "0.97")), float(os.environ.get("MINCOV", "0.6"))
NL = 38
GAIN = float(os.environ.get("GAIN", "0.8"))
known = {(SLOT[k][0], LEOFF[n] + ((1 - SLOT[k][1]) if (n // 2) % 2 else SLOT[k][1])) for n in LEOFF for k in SLOT}
known |= {(df, db) for e in LIM.values() for df, db in e["bits"]}


def window(rb, x, y):
    hb, lane = RW[y]
    fr = np.array([CB[x] + f for f in DF]); bl = [relbyte(hb, lane, k) for k in DB]
    by = np.array([b for b, _ in bl]); ln = np.array([l for _, l in bl])
    return (rb[F0 + FLEN * fr[:, None] + by[None, :]] >> ln[None, :]) & 1


dirs = sorted(d for pat in ("rt_[0-9]*", "lb_[0-9]*") for d in glob.glob(R + "/work/" + pat)
              if os.path.exists(d + "/pips.json") and not d.endswith("_9000"))
TRAIN = int(os.environ.get("TRAIN", str(len(dirs))))
S_src, S_win, S_dir = [], [], []
for d in dirs:
    lines = collections.defaultdict(dict)
    labs = set()
    for a, b in json.load(open(d + "/pips.json")):
        m = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", b)
        if m:
            lines[(int(m[1]), int(m[2]))][int(m[3])] = src_label(a, int(m[1]), int(m[2]))
        m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N", b)
        if m:
            labs.add((int(m[1]), int(m[2])))
    rb = np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)
    for (x, y) in labs:
        if x not in CB:
            continue
        mp = lines.get((x, y), {})
        S_src.append([mp.get(k, "-") for k in range(NL)])
        S_win.append(window(rb, x, y)); S_dir.append(d)
W = np.stack(S_win)
N = len(W)
split = sum(1 for d in S_dir if d in dirs[:TRAIN])
tr = np.array([d in dirs[:TRAIN] for d in S_dir])
print("samples", N, "train", int(tr.sum()))
var = ~(W[tr] == W[tr][0]).all(0)
cand = [(i, j) for i, j in np.argwhere(var) if (DF[i], DB[j]) not in known]
print("varying unknown bits", len(cand))
src = np.array(S_src)


IDS = {}
SID = np.zeros(src.shape, np.int64)
for s_ in range(N):
    for k in range(NL):
        SID[s_, k] = IDS.setdefault(src[s_, k], len(IDS))
NAMES = {v: k for k, v in IDS.items()}
TRI = np.nonzero(tr)[0]
WT = W[TRI]


def fit(cols, bit):
    i, j = bit
    key = SID[TRI, cols[0]] if len(cols) == 1 else SID[TRI, cols[0]] * 100000 + SID[TRI, cols[1]]
    vals = WT[:, i, j].astype(np.int64)
    u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    ones = np.bincount(inv, weights=vals, minlength=len(u))
    big = cnt >= MING
    maj = (ones * 2 >= cnt).astype(int)
    agree = np.where(maj == 1, ones, cnt - ones)
    tot = cnt[big].sum()
    sc = agree[big].sum() / tot if tot else 0.0
    cov = tot / len(TRI)
    table = {}
    for uu, m, g in zip(u, maj, big):
        if g:
            ks = [NAMES[int(uu)]] if len(cols) == 1 else [NAMES[int(uu // 100000)], NAMES[int(uu % 100000)]]
            table["|".join(ks)] = int(m)
    if len(set(table.values())) < 2:
        return 0.0, cov, table, None             # a line set must actually change the bit
    null = max(vals.mean(), 1 - vals.mean())
    if sc - null < GAIN * (1 - null):
        return 0.0, cov, table, None             # must explain most of what the majority misses
    return sc, cov, table, None


out = {}
for (i, j) in cand:
    best = None
    for k in range(NL):
        sc, cov, tab, keys = fit([k], (i, j))
        if cov >= MINCOV and sc >= AGREE and (best is None or sc > best[0]):
            best = (sc, cov, [k], tab, keys)
    if best is None:
        # pairs: only lines whose single fit is already informative
        singles = sorted(range(NL), key=lambda k: -fit([k], (i, j))[0])[:6]
        for k1, k2 in itertools.combinations(singles, 2):
            sc, cov, tab, keys = fit([k1, k2], (i, j))
            if cov >= MINCOV and sc >= AGREE and (best is None or sc > best[0]):
                best = (sc, cov, [k1, k2], tab, keys)
    if best:
        out[f"{DF[i]},{DB[j]}"] = {"lines": best[2], "table": best[3], "score": round(best[0], 4), "cov": round(best[1], 3)}
print("explained bits", len(out), "of", len(cand))
byl = collections.Counter(tuple(e["lines"]) for e in out.values())
print("lines -> bits:", sorted(byl.items(), key=lambda t: -t[1])[:30])
json.dump(out, open(R + "/fuzz/li_joint.json", "w"), indent=0)
if os.environ.get("HOLDOUT"):
    ok = bad = miss = 0
    for s in np.nonzero(~tr)[0]:
        for key, e in out.items():
            df, db = map(int, key.split(","))
            k = "|".join(src[s, c] for c in e["lines"])
            if k not in e["table"]:
                miss += 1; continue
            if e["table"][k] == W[s, DF.index(df), DB.index(db)]:
                ok += 1
            else:
                bad += 1
    print(f"holdout: {ok} right, {bad} wrong, {miss} unseen source combos  -> accuracy {ok / max(1, ok + bad):.4f}")
