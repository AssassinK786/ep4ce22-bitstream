#!/usr/bin/env python3
"""Structural local-line probe with Quartus routing constraints (.rcf), clean-room (Quartus input/outputs only).

Base: a compiled design dir with its database (default work/rcf_test, a copy of bl3_full).
1. quartus_cdb --back_annotate=routing -> top.rcf (complete routing of every net).
2. For every hop LE_BUFFER:X<x>Y<y>S0I<m> -> LOCAL_INTERCONNECT:X<x>Y<y>S0I<k> inside LAB (x, y),
   make a variant that moves that hop to line k' (k' = 0..37, k' != k), re-fit with the .rcf and
   assemble. If the fitter reports an error on that .rcf line the pair (k', m) is illegal.
3. Record the CRAM bit diff against the base for every accepted variant.
Output: fuzz/rcf_probe_<x>_<y>.json  {"base_k": ..., "m": ..., "variants": {k': {"legal": bool, "diff": [[f,b,bit,v]...]}}}
usage: J=2 python3 tools/rcf_probe.py [base_dir] [x y]
"""
import os, sys, re, json, shutil, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES
Q = os.environ.get("QUARTUS_BIN", os.path.expanduser("~/altera/13.1/quartus/bin"))
base = sys.argv[1] if len(sys.argv) > 1 else R + "/work/rcf_test"
X, Y = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (38, 30)
rcf0 = open(base + "/top.rcf").read() if os.path.exists(base + "/top.rcf") else None
if rcf0 is None or os.path.exists(base + "/base.rbf") is False:
    subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=base, capture_output=True)
    rcf0 = open(base + "/top.rcf").read()
    shutil.copy(base + "/top.rbf", base + "/base.rbf")
B = open(base + "/base.rbf", "rb").read()

# hops LE_BUFFER Im -> LOCAL_INTERCONNECT Ik in LAB (X, Y): the LOCAL_INTERCONNECT line that follows a
# LE_BUFFER line (possibly through a label) inside one signal block
hops = []
lines = rcf0.splitlines()
for i, l in enumerate(lines):
    m = re.search(rf"LOCAL_INTERCONNECT:X{X}Y{Y}S0I(\d+);", l)
    if not m:
        continue
    for j in (i - 1,):
        mb = re.search(rf"LE_BUFFER:X{X}Y{Y}S0I(\d+);", lines[j])
        if mb:
            hops.append((i, int(mb[1]), int(m[1])))
            break
print("hops", hops)


def diff(a, b):
    out = []
    for f in range(NFRAMES):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            x = a[o + byte] ^ b[o + byte]
            for bit in range(8):
                if x >> bit & 1:
                    out.append([f, byte, bit, (b[o + byte] >> bit) & 1])
    return out


def variant(job):
    li, m, k, k2 = job
    d = f"{base}_v_{li}_{k2}"
    if os.path.exists(d + "/result.json"):
        return json.load(open(d + "/result.json"))
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns("*_v_*"))
    L = list(lines)
    L[li] = L[li].replace(f"S0I{k};", f"S0I{k2};")
    open(d + "/top.rcf", "w").write("\n".join(L) + "\n")
    r = subprocess.run([Q + "/quartus_fit", "top"], cwd=d, capture_output=True, text=True)
    err = re.search(rf"Error on line number {li + 1} in Routing Constraints File", r.stdout) is not None
    res = {"li": li, "m": m, "k": k, "k2": k2, "legal": not err and r.returncode == 0, "diff": []}
    if res["legal"]:
        subprocess.run([Q + "/quartus_asm", "top"], cwd=d, capture_output=True)
        res["diff"] = diff(B, open(d + "/top.rbf", "rb").read())
    json.dump(res, open(d + "/result.json", "w"))
    for sub in ("db", "incremental_db"):
        shutil.rmtree(f"{d}/{sub}", ignore_errors=True)
    return res


if __name__ == "__main__":
    jobs = [(li, m, k, k2) for li, m, k in hops for k2 in range(38) if k2 != k]
    out = []
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        for res in ex.map(variant, jobs):
            out.append(res)
            print(res["m"], res["k"], "->", res["k2"], "legal" if res["legal"] else "illegal", len(res["diff"]), flush=True)
    json.dump(out, open(R + f"/fuzz/rcf_probe_{X}_{Y}.json", "w"))
