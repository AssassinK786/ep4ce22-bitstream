#!/usr/bin/env python3
"""Tag solver for routing specimens from route_fuzz.py.

Tags per specimen: every (from, to) hop in pips.json, plus 'SITE:<x>_<y>_<n>' for used LEs.
Bits: every CRAM data bit that varies across specimens (frame CRCs and the header excluded).
A bit is assigned to a tag when its 0/1 pattern over specimens equals the tag's presence
pattern (or its inverse). Unmatched bits are reported with their best candidates.

usage: python3 tools/route_solve.py [work/rt_*] -> fuzz/route_pips.json
"""
import os, sys, glob, json, collections
import numpy as np

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES

dirs = sorted(d for d in (sys.argv[1:] or glob.glob(R + "/work/rt_[0-9]*")) if os.path.exists(d + "/pips.json"))
dirs = [d for d in dirs if not d.endswith("rt_9000")]
n = len(dirs)
print("specimens", n)

# data-bit mask: frame bytes 1..295 only
mask = np.zeros(F0 + FLEN * NFRAMES, bool)
for f in range(NFRAMES):
    o = F0 + FLEN * f
    mask[o + 1:o + 296] = True
idx = np.nonzero(mask)[0]

bits = np.stack([np.unpackbits(np.frombuffer(open(d + "/top.rbf", "rb").read(), np.uint8)[idx], bitorder="little") for d in dirs])
var = np.nonzero(bits.any(0) & ~bits.all(0))[0]
print("varying bits", len(var))

tags = collections.defaultdict(lambda: np.zeros(n, bool))
for i, d in enumerate(dirs):
    for a, b in json.load(open(d + "/pips.json")):
        tags[f"{a}->{b}"][i] = True
    for x, y, nn in json.load(open(d + "/sites.json")):
        tags[f"SITE:{x}_{y}_{nn}"][i] = True
print("tags", len(tags))

# hash tag patterns
pat = collections.defaultdict(list)
for t, v in tags.items():
    pat[np.packbits(v).tobytes()].append(t)


def where(k):
    byte = idx[k // 8]
    f, o = divmod(byte - F0, FLEN)
    return f, int(o), int(k % 8)


out, unmatched, ambiguous = {}, 0, 0
for k in var:
    v = bits[:, k].astype(bool)
    hit = pat.get(np.packbits(v).tobytes())
    inv = False
    if not hit:
        hit = pat.get(np.packbits(~v).tobytes())
        inv = True
    loc = "%d:%d:%d" % where(k)
    if not hit:
        unmatched += 1
        continue
    if len(hit) > 1:
        ambiguous += 1
    out[loc] = {"tags": hit, "inverted": inv, "count": int(v.sum())}

print(f"matched {len(out)} (ambiguous {ambiguous}), unmatched {unmatched}")
kinds = collections.Counter()
for e in out.values():
    if len(e["tags"]) == 1:
        a, b = e["tags"][0].split("->") if "->" in e["tags"][0] else (e["tags"][0], "")
        kinds[(a.split("_X")[0], b.split("_X")[0] + ("." + b.split(".")[-1] if "." in b else ""))] += 1
for k, c in kinds.most_common(25):
    print(f"  {c:5d}  {k[0]} -> {k[1]}")
json.dump(out, open(R + "/fuzz/route_pips.json", "w"), indent=0)

# ---- pass 2: bits that are the OR of several tags (shared mux bits) ----
names = list(tags)
U = np.packbits(np.stack([tags[t] for t in names]), axis=1)          # tags x bytes
cnt = np.array([tags[t].sum() for t in names])
or_out, still = {}, 0
for k in var:
    loc = "%d:%d:%d" % where(k)
    if loc in out:
        continue
    v = bits[:, k].astype(bool)
    for inv in (False, True):
        w = ~v if inv else v
        if w.sum() == 0:
            continue
        wp = np.packbits(w)
        sub = ~np.any(U & ~wp, axis=1) & (cnt > 0)                       # tag present => bit set
        if not sub.any():
            continue
        cand = np.nonzero(sub)[0]
        orv = np.bitwise_or.reduce(U[cand], axis=0)
        if np.array_equal(orv, wp):
            # keep the minimal cover: drop tags covered by others (greedy by count)
            cand = sorted(cand, key=lambda c: -cnt[c])
            cov, keep = np.zeros_like(wp), []
            for c in cand:
                if np.any(U[c] & ~cov):
                    keep.append(names[c]); cov |= U[c]
            or_out[loc] = {"tags": keep, "inverted": inv, "or": True, "count": int(w.sum())}
            break
    else:
        still += 1
print(f"pass 2: OR-of-tags matched {len(or_out)}, still unmatched {still}")
sizes = collections.Counter(min(len(e['tags']), 9) for e in or_out.values())
print("  cover sizes:", dict(sorted(sizes.items())))
out.update(or_out)
json.dump(out, open(R + "/fuzz/route_pips.json", "w"), indent=0)
