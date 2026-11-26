#!/usr/bin/env python3
"""Decode routing-mux select codes in LAB-relative coordinates, pooling every LAB and specimen.

MODE=lim : sinks are LUT inputs      LCCOMB_X_Y_Nn.data[abcd]      key N<n>.<port>
MODE=li  : sinks are local lines     LOCAL_INTERCONNECT_X_Y_N0_I<k> key I<k>

A relative bit (dframe, dbyte) belongs to a sink's mux when, for every source seen >= MINS
times, at least AGREE of its samples agree on the bit, and the majority values differ between
sources. Row bytes wrap per rlabel.relbyte.

TRAIN=<n> uses only the first n specimens; HOLDOUT=1 then tests the rest.
"""
import os, sys, re, glob, json, collections
import numpy as np

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import src_label, relbyte

MODE = os.environ.get("MODE", "li")
MINS = int(os.environ.get("MINS", "3"))
AGREE = float(os.environ.get("AGREE", "0.9"))
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}
RW = {int(k): tuple(v) for k, v in G["row"].items()}
DF = range(*map(int, os.environ.get("DFR", "-14,26").split(",")))
DB = range(*map(int, os.environ.get("DBR", "-8,80").split(",")))
KEYS = set(os.environ["KEYS"].split(",")) if os.environ.get("KEYS") else None

if MODE == "lim":
    EDGE = re.compile(r"^LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$")
    key_of = lambda m: f"N{m[3]}.{m[4]}"
else:
    EDGE = re.compile(r"^LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$")
    key_of = lambda m: f"I{m[3]}"

ALL = sorted(d for d in glob.glob(R + "/work/rt_[0-9]*") if os.path.exists(d + "/pips.json") and not d.endswith("rt_9000"))
TRAIN = int(os.environ.get("TRAIN", str(len(ALL))))
OUT = os.environ.get("OUT", R + f"/fuzz/{MODE}_codes.json")


LANES = range(*map(int, os.environ.get("LANES", "0,1").split(",")))   # lane offsets read per byte


def window(rb, x, y):
    hb, lane = RW[y]
    fr = np.array([CB[x] + f for f in DF])
    bl = [relbyte(hb, lane, k) for k in DB]
    by = np.array([b for b, _ in bl]); ln = np.array([l for _, l in bl])
    raw = rb[F0 + FLEN * fr[:, None] + by[None, :]]
    w = np.stack([(raw >> ((ln[None, :] + d) % 8)) & 1 for d in LANES], axis=-1)
    return w.reshape(len(DF), len(DB) * len(LANES)) if len(LANES) > 1 else w[..., 0]


def samples_of(dirs):
    for d in dirs:
        rb = np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)
        win = {}
        for a, b in json.load(open(d + "/pips.json")):
            m = EDGE.match(b)
            if not m or (KEYS and key_of(m) not in KEYS):
                continue
            x, y = int(m[1]), int(m[2])
            if y not in RW or x not in CB:
                continue
            if (x, y) not in win:
                win[(x, y)] = window(rb, x, y)
            yield key_of(m), src_label(a, x, y), win[(x, y)]


def decode(dirs):
    S = collections.defaultdict(list)
    for k, s, w in samples_of(dirs):
        S[k].append((s, w))
    out = {}
    for key, lst in S.items():
        cnt = collections.Counter(s for s, _ in lst)
        good = [s for s in cnt if cnt[s] >= MINS]
        if not good:
            out[key] = {"bits": [], "codes": {}, "samples": len(lst), "sources": len(cnt)}
            continue
        M = np.stack([w for _, w in lst]); lab = [s for s, _ in lst]
        ok = np.ones(M.shape[1:], bool); vals = {}
        for s in good:
            sub = M[[i for i, l in enumerate(lab) if l == s]]
            frac = sub.mean(0)
            ok &= np.maximum(frac, 1 - frac) >= AGREE
            vals[s] = (frac >= 0.5).astype(np.uint8)
        first = np.stack([vals[s] for s in good])
        idx = np.argwhere(ok & ~(first == first[0]).all(0))
        out[key] = {"bits": [[DF[i], DB[j // len(LANES)], LANES[j % len(LANES)]] if len(LANES) > 1 else [DF[i], DB[j]] for i, j in idx],
                    "codes": {s: "".join(str(int(vals[s][i, j])) for i, j in idx) for s in good},
                    "samples": len(lst), "sources": len(cnt)}
    return out


def holdout(model, dirs):
    st = collections.Counter(); fails = collections.Counter(); unseen = collections.Counter()
    pos = {k: [DB.index(db) + 0 for _, db in e["bits"]] for k, e in model.items()}
    for k, s, w in samples_of(dirs):
        e = model.get(k)
        if not e or not e["bits"]:
            st["nomodel"] += 1; continue
        if s not in e["codes"]:
            st["unseen"] += 1; unseen[s] += 1; continue
        got = "".join(str(int(w[b[0] - DF[0], (b[1] - DB[0]) * len(LANES) + (b[2] - LANES[0] if len(b) > 2 else 0)])) for b in e["bits"])
        if got == e["codes"][s]:
            st["ok"] += 1
        else:
            st["bad"] += 1; fails[(k, s)] += 1
    return st, fails, unseen


if __name__ == "__main__":
    model = decode(ALL[:TRAIN])
    keys = sorted(model, key=lambda k: [int(t) if t.isdigit() else t for t in re.findall(r"\d+|\D+", k)])
    for k in keys:
        e = model[k]
        print(f"{k:10s} samples {e['samples']:5d} sources {e['sources']:3d} (>={MINS}: {len(e['codes']):2d}) "
              f"bits {len(e['bits']):2d} distinct codes {len(set(e['codes'].values())):2d}")
    json.dump(model, open(OUT, "w"), indent=1)
    if os.environ.get("HOLDOUT"):
        st, fails, unseen = holdout(model, ALL[TRAIN:])
        tot = st["ok"] + st["bad"]
        print(f"HOLDOUT {len(ALL) - TRAIN} specimens: {st['ok']}/{tot} exact = {st['ok'] / max(tot, 1):.4f}; "
              f"unseen-source {st['unseen']}; no model {st['nomodel']}")
        for f, c in fails.most_common(12):
            print("  fail", c, f)
        for f, c in unseen.most_common(6):
            print("  unseen", c, f)
