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
env = dict(os.environ, DESIGN=name, TREE=os.environ.get("TREE", "clock_tree_pnr.json"))
r = subprocess.run([sys.executable, R + "/tools/blinky_gen.py"], env=env, capture_output=True, text=True)
if r.returncode:
    sys.exit(r.stderr[-800:])
conflicts = [l for l in r.stdout.splitlines() if l.startswith("conflict")]
rb = Rbf.load(f"{R}/work/{name}_model_only.rbf")
ALL = json.load(open(R + "/fuzz/io_paths_all.json"))
used = [p for p in info.get("inputs", []) + info.get("outputs", []) if p != "A15"]
setbits = {}
for pin in (["bundle"] if used else []):     # the pins were measured together: one table for all of them
    for e in ALL["bits"]:
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
if "A15" not in info.get("outputs", []):
    print("emit: note: LED0 (A15) unused, but the models always emit its output path (fuzz/paths.json)")
rb.fix_crcs()
out = f"{R}/work/{name}_open.rbf"
rb.save(out)
print(f"emit: {name}: pins {sorted(used)} + A15/R8 by the models; {len(setbits)} table bits; "
      f"conflicts {len(conflicts)}; container {rb.check() or 'OK'} -> {out}")
for c in conflicts[:10]:
    print("  ", c)
