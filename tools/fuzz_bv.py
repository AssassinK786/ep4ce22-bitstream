#!/usr/bin/env python3
"""Training designs: the bl2 counter (blinky2_design.py) placed at other LAB pairs, with complete
STA hops (reg->reg pairs). work/bv_<k>/ ; usage: python3 tools/fuzz_bv.py"""
import os, sys, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from route_fuzz import STA, parse, Q
PAIRS = [(20, 11, 20, 10), (30, 26, 30, 25), (12, 6, 12, 5), (25, 30, 25, 29), (36, 20, 36, 19),
         (8, 26, 8, 25), (38, 30, 38, 29), (36, 32, 36, 31), (20, 10, 20, 11), (30, 25, 30, 26)]


def run(k):
    xa, ya, xb, yb = PAIRS[k]
    name = f"bv_{k:02d}"; d = f"{R}/work/{name}"
    if os.path.exists(d + "/pips.json"):
        return name, "cached"
    subprocess.run([sys.executable, R + "/tools/blinky2_design.py", name, str(xa), str(ya), str(xb), str(yb)], capture_output=True)
    r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True, env=dict(os.environ, EDA="1"))
    if r.returncode:
        return name, "FAIL " + (r.stdout + r.stderr)[-200:].replace("\n", " ")
    open(d + "/sta.tcl", "w").write(STA.replace("-from_clock clk -to_clock clk ", ""))
    subprocess.run([Q + "/quartus_sta", "-t", "sta.tcl"], cwd=d, capture_output=True)
    json.dump(sorted(parse(d + "/paths.rpt")), open(d + "/pips.json", "w"))
    subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof", f"{d}/paths.rpt"])
    return name, "ok"


if __name__ == "__main__":
    with cf.ThreadPoolExecutor(2) as ex:
        for n, r in ex.map(run, range(len(PAIRS))):
            print(n, r, flush=True)
