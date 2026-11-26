#!/usr/bin/env python3
"""Structural local-line code table from the .rcf experiments (src_sweep.py, force_probe.py).

Per LAB result file: drop the destination-side bits common to every variant of that LAB, keep the rest as
the code of the (line, source) of that variant. Codes from different LABs must agree (LAB-relative).
Source labels use rlabel.src_label conventions: "LE_BUFFER_I<m>" (own LAB), "LE_BUFFER@dx,dy_I<m>",
"R4@dx,dy_I<i>", "C4@dx,dy_I<i>".
Output: fuzz/li_struct.json {"<line>|<source>": [[df, db, v], ...]} and a consistency report.
"""
import os, sys, glob, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
table = collections.defaultdict(list)          # key -> list of (lab, bits)
for f in glob.glob(R + "/fuzz/force2w_*.json"):                   # single-branch forced hops: code = bits set
    lab = os.path.basename(f).rsplit(".", 1)[0]
    for r in json.load(open(f)):
        if not r.get("legal") or "bits" not in r:
            continue
        dy, m, k = r["pair"]
        key = f"{k}|LE_BUFFER_I{m}" if dy == 0 else f"{k}|LE_BUFFER@0,{dy}_I{m}"
        on = sorted(tuple(b) for b in r["bits"] if b[2] == 1)
        table[key].append((lab, on))            # empty = the line's default (all-zero) selection
        # the natural route of the same net (bits that went 1 -> 0) is the code of the natural hop
        x, y = map(int, lab.split("_")[-2:])
        n = m - m % 2; dsl = 2 if (dy == 0 and n == 0) else 0
        base = f"{R}/work/f2_{x}_{y}_{x}_{y + dy}_{n}_d{dsl}_X/top.rcf"
        if os.path.exists(base):
            import re as _re
            blk = _re.search(r"signal_name = rs \{(.*?)\n\}", open(base).read(), _re.S).group(1)
            el = _re.findall(r"(\w+):X(\d+)Y(\d+)S0I(\d+);", blk)
            hops = [(int(e[3]), el[i - 1]) for i, e in enumerate(el) if e[0] == "LOCAL_INTERCONNECT" and int(e[1]) == x and int(e[2]) == y and i]
            off = sorted(tuple(b[:2]) + (1,) for b in r["bits"] if b[2] == 0)
            if len(hops) == 1 and off:
                k0, (kind, sx, sy, si) = hops[0]
                dx_, dy_ = int(sx) - x, int(sy) - y
                lab0 = f"{kind}_I{si}" if (dx_, dy_) == (0, 0) else f"{kind}@{dx_},{dy_}_I{si}"
                table[f"{k0}|{lab0}"].append((lab + "-natural", off))
for f in glob.glob(R + "/fuzz/src_sweep_*.json"):
    lab = os.path.basename(f).rsplit(".", 1)[0]
    rows = json.load(open(f))
    entries = []
    for r in rows:
        if "hops" in r:                                          # sweep: the hop that carries the net
            sx, sy, sn = r["src"]
            x, y = map(int, lab.split("_")[-2:])
            cand = [h for h in r["hops"] if not h[1].startswith(("R4@1,0_I22", "C4@0,-3_I11"))]
            if len(cand) != 1 or (sx, sy) == (x, y):
                continue
            key = f"{cand[0][0]}|{cand[0][1]}"
        else:
            if not r.get("legal"):
                continue
            dy, m, k = r["pair"]
            key = f"{k}|LE_BUFFER_I{m}" if dy == 0 else f"{k}|LE_BUFFER@0,{dy}_I{m}"
        entries.append((key, {tuple(b) for b in r["bits"]}))
    if not entries:
        continue
    common = set.intersection(*[b for _, b in entries]) if len(entries) > 2 else set()
    for key, bits in entries:
        table[key].append((lab, sorted(bits - common)))
# tied-base measurements (tools/tied_probe.py): the code is what every LAB has in common
tied = collections.defaultdict(list)
if os.path.exists(R + "/fuzz/tied.json"):
    for r in json.load(open(R + "/fuzz/tied.json")):
        if r["key"]:
            tied[r["key"]].append({tuple(b) for b in r["bits"]})
for key, sets in tied.items():
    if len(sets) >= 3:
        table[key] = [("tied", sorted(set.intersection(*sets)))]
# vertical link from the LAB below (tools: force3 natural builds vs tied bases, common to 3 LABs)
if os.path.exists(R + "/fuzz/vbelow_code.json"):
    table["29|LE_BUFFER@0,-1_I1"] = [("tied-vbelow", sorted(tuple(b) for b in json.load(open(R + "/fuzz/vbelow_code.json"))))]
out, agree, disagree = {}, 0, 0
for key, obs in table.items():
    codes = {tuple(map(tuple, b)) for _, b in obs}
    if len(codes) == 1:
        out[key] = [list(b) for b in obs[0][1]]; agree += len(obs) > 1
    else:
        disagree += 1
        print("DISAGREE", key, obs)
print(f"(line, source) codes: {len(out)}; seen at >1 LAB and identical: {agree}; disagreeing: {disagree}")
json.dump(out, open(R + "/fuzz/li_struct.json", "w"), indent=0)
