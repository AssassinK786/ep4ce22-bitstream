#!/usr/bin/env python3
"""Bitstream for a pnr.py design directory: the decoded bit models (blinky_gen.py, model-only output)
plus the measured pin tables (fuzz/io_paths.json) for the pins the design uses.
usage: emit.py NAME   -> work/NAME_open.rbf"""
import os, sys, json, subprocess
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, R + "/tools")
from rbf import Rbf, F0, FLEN, PERIPH

name = sys.argv[1]
d = f"{R}/work/{name}"
info = json.load(open(d + "/pnr.json"))
# clock tree measured for exactly the LABs with registers (an unused LAB's row enable stays off)
_pos = {int(k): tuple(v) for k, v in info["placement"].items()}
_fflabs = {(_pos[e["id"]][0], _pos[e["id"]][1]) for e in info["les"] if e["ff"]}
_ys = {y for x, y in _fflabs}
_tree = {frozenset({31, 32}): "clock_tree2.json", frozenset({32}): "clock_tree2.json",
         frozenset({30, 31}): "clock_tree3.json", frozenset({30}): "clock_tree3.json"}.get(frozenset(_ys), "clock_tree_pnr.json")
if 31 not in _ys and _ys:
    pass                          # LED0's LAB (38,31) is clocked through the LED register anyway
env = dict(os.environ, DESIGN=name, TREE=os.environ.get("TREE", _tree))
r = subprocess.run([sys.executable, R + "/tools/blinky_gen.py"], env=env, capture_output=True, text=True)
if r.returncode:
    sys.exit(r.stderr[-800:])
conflicts = [l for l in r.stdout.splitlines() if l.startswith("conflict")]
rb = Rbf.load(f"{R}/work/{name}_model_only.rbf")
ALL = json.load(open(R + "/fuzz/" + {"all": "io_paths_all.json", "out31": "io_paths_out31.json"}[info.get("bundle", "all")]))
used = [p for p in info.get("inputs", []) + info.get("outputs", []) if p != "A15"]
setbits = {}
# Bundles are residuals measured against the merged 3-LAB clock tree; entries on clock-tree positions are
# that tree's row enables for LABs the probe design didn't clock, not pin bits: never take them from a bundle.
TREEPOS = set()
for _f in ("clock_tree2.json", "clock_tree3.json", "clock_tree_pnr.json"):
    for _t in json.load(open(R + "/fuzz/" + _f)).values():
        TREEPOS |= {tuple(e[:4]) for e in _t if e[0] == "cram"}
skipped = 0
for pin in (["bundle"] if used else []):     # the pins were measured together: one table for all of them
    for e in ALL["bits"]:
        if tuple(e[:4]) in TREEPOS:
            skipped += 1
            continue
        if e[0] == "cram":
            key, (f, b, k, v) = ("c", e[1], e[2], e[3]), e[1:]
            o = F0 + FLEN * f + b
            rb.d[o] = (rb.d[o] & ~(1 << k)) | (v << k)
        else:
            key, (i, k, v) = ("p", e[1], e[2]), e[1:]
            for j in range(4):
                o = PERIPH + 4 * i + j
                rb.d[o] = (rb.d[o] & ~(1 << k)) | (v << k)
        if key in setbits and setbits[key][1] != v:
            conflicts.append(f"pin tables {setbits[key][0]} and {pin} disagree at {key}")
        setbits[key] = (pin, v)
INV = json.load(open(R + "/fuzz/io_out_invert.json")) if os.path.exists(R + "/fuzz/io_out_invert.json") else {}
for pin in info.get("inverted_pins", []):       # I/O-cell output inversion (power-up-high register at the slot)
    _, f, b, k, v = INV[pin]
    o = F0 + FLEN * f + b
    rb.d[o] = (rb.d[o] & ~(1 << k)) | (v << k)
# carry chains: every LE that takes a carry in has its LUT input C on cin: bit (-1, LEOFF[n] + (k even)) = 0
from rlabel import relbyte
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}
pos = {int(k): tuple(v) for k, v in info["placement"].items()}
ncin = 0
for ch in info.get("chains", []):
    for le in ch[1:]:
        x, y, n = pos[le]
        hb, lane = RW[y]
        b, ln = relbyte(hb, lane, LEOFF[n] + (1 if (n // 2) % 2 == 0 else 0))
        o = F0 + FLEN * (CB[x] - 1) + b
        rb.d[o] &= ~(1 << ln)
        ncin += 1
if ncin:
    print(f"emit: {ncin} carry-in LEs (LUT input C on cin)")
if "A15" not in info.get("outputs", []):
    print("emit: note: LED0 (A15) unused, but the models always emit its output path (fuzz/paths.json)")
rb.fix_crcs()
out = f"{R}/work/{name}_open.rbf"
rb.save(out)
print(f"emit: clock tree {env['TREE']} for LAB rows {sorted(_ys)}; bundle entries on clock-tree positions skipped: {skipped}")
print(f"emit: {name}: pins {sorted(used)} + A15/R8 by the models; inverted {info.get('inverted_pins', [])}; {len(setbits)} table bits; "
      f"conflicts {len(conflicts)}; container {rb.check() or 'OK'} -> {out}")
for c in conflicts[:10]:
    print("  ", c)
