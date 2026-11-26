#!/usr/bin/env python3
"""Vote: LE combout -> LE_BUFFER bits per slot (labels by construction).
X: 16-LE comb chain in LAB (x,y); every LE also feeds the same slot's LUT in LAB (x,y-1) (direct link,
   through its LE_BUFFER); the lower LAB's LUTs XOR into the pin. Y1/Y2: the same upper chain with
   local connections only (lower LAB unused), masks 6666 / 9999.
usage: python3 tools/fuzz_vote3.py [solve]"""
import os, sys, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from fuzz_vote import vote
LABS = [(20, 11), (30, 26), (12, 6)]


def design(tag):
    _, x, y, kind = tag.split("_"); x, y = int(x), int(y)
    mask = "9999" if kind == "Y2" else "6666"
    v = ["module top(input din, output dout);"]
    q = ["set_location_assignment PIN_M1 -to din", "set_location_assignment PIN_A15 -to dout"]
    prev = "din"; low = []
    for n in range(0, 32, 2):
        v.append(f"  wire c{n}; cycloneive_lcell_comb #(.lut_mask(16'h{mask})) l{n} (.dataa({prev}),.datab(din),.datac(1'b0),.datad(1'b0),.combout(c{n}));")
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l{n}")
        prev = f"c{n}"
        if kind == "X":
            lp = low[-1] if low else "din"
            v.append(f"  wire e{n}; cycloneive_lcell_comb #(.lut_mask(16'h6666)) m{n} (.dataa(c{n}),.datab({lp}),.datac(1'b0),.datad(1'b0),.combout(e{n}));")
            q.append(f"set_location_assignment LCCOMB_X{x}_Y{y-1}_N{n} -to m{n}")
            low.append(f"e{n}")
    out = prev if kind != "X" else f"{prev} ^ {low[-1]}"
    v += [f"  assign dout = {out};", "endmodule"]
    d = f"{R}/work/vt_{tag}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


TAGS = [f"cb_{x}_{y}_{k}" for x, y in LABS for k in ("X", "Y1", "Y2")]


def run(tag):
    d = design(tag)
    if not os.path.exists(d + "/top.rbf"):
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
        if r.returncode:
            return tag, "FAIL " + (r.stdout + r.stderr)[-250:].replace("\n", " ")
    return tag, "ok"


if __name__ == "__main__":
    if sys.argv[1:] == ["solve"]:
        G = json.load(open(R + "/fuzz/lab_grid.json"))
        CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
        lin = lambda b, l: l * 294 + (295 - b)
        common = None
        for x, y in LABS:
            rel = {}
            for e in vote(f"cb_{x}_{y}_X", f"cb_{x}_{y}_Y1", f"cb_{x}_{y}_Y2"):
                if e[0] != "cram":
                    continue
                _, f, byte, bit, val = e
                df, db = f - CB[x], lin(byte, bit) - lin(*RW[y])
                if -14 <= df <= 25 and 0 <= db < 70:
                    rel[(df, db)] = val
            print((x, y), len(rel), sorted(rel.items()))
            common = rel if common is None else {k: v for k, v in common.items() if rel.get(k) == v}
        print("common", len(common), sorted(common.items()))
        json.dump([[df, db, v] for (df, db), v in sorted(common.items())], open(R + "/fuzz/c2buf_vote.json", "w"))
    else:
        with cf.ThreadPoolExecutor(2) as ex:
            for tag, res in ex.map(run, TAGS):
                print(tag, res, flush=True)
