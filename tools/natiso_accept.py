#!/usr/bin/env python3
"""Accept column chains from natiso results (tools/col_vert.py natiso, work/cvn_<X>_<ys>_<yd>_<sn>/result.json).

Each natiso code = bits 1 in the natural build, 0 in the tied-off base. Besides the chain it contains
deterministic (seed-independent, checked 2026-11-27) DESIGN artefacts of the tie-off base, which vary with
the dest row: the top-periphery output-pin routes (absolute lin < row 33's base), the constant (19,-2)/(21,-1),
and dest-side reshuffles (the dt input moves to another local line, LUT input-mux bits). So codes are never
identical row to row. Acceptance instead:
  core   = intersection of the cleaned codes over every observed dest row (>= 3 rows)
  LOO    = the core from any n-1 rows equals the full core (no artefact survives by coincidence)
  guard  = no core bit is present in >= 40 % of all results at every one of its rows (design artefact)
  nonempty core (an empty core is "not measured", never validated)
Accepted entries are phase-free ("phase": None, "validated": True, "method": "natiso-core"); they replace
earlier entries of the same chain. Chains not accepted keep their earlier entry; with --with-unvalidated
the remaining single-row cleaned codes are added as "validated": False (only if no entry exists).
usage: python3 tools/natiso_accept.py [X] [--with-unvalidated]
"""
import os, sys, glob, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from wire_harvest import LIN
X = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 38
G = json.load(open(R + "/fuzz/lab_grid.json")); RW = {int(k): tuple(v) for k, v in G["row"].items()}
ART = {(19, -2), (21, -1)}
TOP = LIN(*RW[max(RW)])
res = []
for p in glob.glob(f"{R}/work/cvn_{X}_*/result.json"):
    if os.path.basename(os.path.dirname(p)).count("_") != 4:      # tagged test runs (CVN_TAG)
        continue
    r = json.load(open(p))
    if r["chain"] and r["code"] is not None and r["chain"][0][0] == "LE_BUFFER" and r["chain"][-1][0] == "LOCAL_INTERCONNECT":
        r["L0"] = LIN(*RW[r["yd"]]); res.append(r)
n = collections.Counter(r["yd"] for r in res)
cnt = collections.defaultdict(collections.Counter)
for r in res:
    for b in map(tuple, r["code"]):
        cnt[r["yd"]][b] += 1
clean = lambda r: frozenset(b for b in map(tuple, r["code"]) if b not in ART and b[1] + r["L0"] >= TOP)
groups = collections.defaultdict(list)
for r in res:
    groups[json.dumps(r["chain"])].append(r)
acc, single, rej = [], [], collections.Counter()
LOCAL = lambda b: 12 <= b[0] <= 22 and -400 <= b[1] <= 400   # dest line mux / C4 driver area of the chain
def common(y, b):                                  # bit seen in >= 25 % of all results at dest row y = design artefact
    return cnt[y][b] >= 0.25 * n[y]
def try_group(o):
    """core over the rows of o, or (None, reason). Every row's unexplained local residue must be empty."""
    yds = sorted({r["yd"] for r in o})
    core = frozenset.intersection(*[clean(r) for r in o])
    if not core:
        return None, "empty core"
    if len(yds) >= 3 and any(frozenset.intersection(*[clean(r) for r in o if r["yd"] != y]) != core for y in yds):
        return None, "leave-one-out"
    if any(all(cnt[y][b] >= 0.4 * n[y] for y in yds) for b in core):
        return None, "artefact guard"
    for r in o:
        if [b for b in clean(r) - core if LOCAL(b) and not common(r["yd"], b)]:
            return None, "unexplained local residue"
    return core, None
for ch, o in groups.items():
    yds = sorted({r["yd"] for r in o})
    if len(yds) == 1:
        single.append({"chain": json.loads(ch), "x": X, "phase": yds[0] % 4, "rows": yds,
                       "bits": sorted(map(list, clean(o[0]))), "validated": False})
    if len(yds) < 3:
        rej["< 3 rows"] += 1; continue
    core, why = try_group(o)
    if core is not None:
        acc.append({"chain": json.loads(ch), "x": X, "phase": None, "rows": yds, "bits": sorted(map(list, core)),
                    "validated": True, "method": "natiso-core"}); continue
    # row-parity dependent codes (seen: line-10 select alternates (13,44)/(13,45)): split by yd % 2,
    # each half needs >= 2 rows; stored as two phase entries each (phase = yd % 4 values of that parity)
    halves = {par: [r for r in o if r["yd"] % 2 == par] for par in (0, 1)}
    res2 = {par: try_group(h) if len({r["yd"] for r in h}) >= 2 else (None, "< 2 rows") for par, h in halves.items()}
    if all(c is not None for c, _ in res2.values()):
        for par, (c, _) in res2.items():
            for ph in (par, par + 2):
                acc.append({"chain": json.loads(ch), "x": X, "phase": ph, "rows": sorted({r["yd"] for r in halves[par]}),
                            "bits": sorted(map(list, c)), "validated": True, "method": "natiso-core-parity"})
        rej["accepted by parity"] += 1; continue
    rej[why] += 1
print(f"results {len(res)}, chains {len(groups)}: accepted {len(acc)}; rejected {dict(rej)}")
p = f"{R}/fuzz/col_vert_{X}.json"
prev = json.load(open(p)) if os.path.exists(p) else []
ka = {json.dumps(e["chain"]) for e in acc} | {json.dumps(e["chain"]) for e in prev if e.get("method", "").startswith("natiso-core")}
merged = acc + [e for e in prev if json.dumps(e["chain"]) not in ka]   # earlier natiso-core entries are recomputed
if "--with-unvalidated" in sys.argv:
    have = {json.dumps(e["chain"]) for e in merged}
    merged += [e for e in single if json.dumps(e["chain"]) not in have]
json.dump(merged, open(p, "w"), indent=0)
print("written", p, len(merged), "entries,", sum(1 for e in merged if e.get("validated", True)), "validated")
