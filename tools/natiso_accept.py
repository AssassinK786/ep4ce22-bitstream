#!/usr/bin/env python3
"""Accept vertical chains from tools/col_vert.py natiso results (work/cvn_<X>_*).

Each result = a chain Quartus chose naturally + its code (natural build vs pinned base). Codes minus the
constant base artefact (19,-2)/(21,-1). Per destination-relative chain:
  validated   : seen at >= 2 destination rows, identical codes at all of them (row-to-row agreement)
  unvalidated : seen at one row only (kept separately; the board / later rows confirm them)
Merges into fuzz/col_vert_<X>.json (keeps earlier accepted entries); unvalidated ones get "validated": false.
usage: python3 tools/natiso_accept.py [X] [--with-unvalidated]
"""
import os, sys, glob, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 38
ART = {(19, -2), (21, -1)}
groups = collections.defaultdict(list)
for p in glob.glob(f"{R}/work/cvn_{X}_*/result.json"):
    r = json.load(open(p))
    if r["chain"] and r["code"] is not None and r["chain"][0][0] == "LE_BUFFER" and r["chain"][-1][0] == "LOCAL_INTERCONNECT":
        groups[json.dumps(r["chain"])].append((r["yd"], frozenset(map(tuple, r["code"])) - ART))
val, unval, bad = [], [], 0
for ch, obs in groups.items():
    rows = sorted({y for y, _ in obs})
    codes = {c for _, c in obs}
    phases = {y % 4 for y in rows}
    entry = {"chain": json.loads(ch), "x": X, "phase": None if len(phases) > 1 else phases.pop(), "rows": rows}
    if len(codes) == 1:
        entry["bits"] = sorted(next(iter(codes)))
        if len(rows) >= 2:
            entry["validated"] = True; val.append(entry)
        else:
            entry["validated"] = False; unval.append(entry)
    else:
        bad += 1
print(f"chains: {len(groups)}; validated (identical at >= 2 rows): {len(val)}; single-row: {len(unval)}; disagreeing: {bad}")
p = f"{R}/fuzz/col_vert_{X}.json"
prev = json.load(open(p)) if os.path.exists(p) else []
new = val + (unval if "--with-unvalidated" in sys.argv else [])
keys = {(json.dumps(e["chain"]), e["phase"]) for e in new}
merged = new + [e for e in prev if (json.dumps(e["chain"]), e["phase"]) not in keys]
json.dump(merged, open(p, "w"), indent=0)
print("written", p, len(merged), "entries")
