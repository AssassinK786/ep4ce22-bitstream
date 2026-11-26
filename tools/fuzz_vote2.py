#!/usr/bin/env python3
"""Votes for blinky v2 (labels by construction).
  ff_<x>_<y>_{X,Y1,Y2}: 16-LE chain in LAB (x,y); X = every LE LUT -> FF, q to the next LE;
      Y1/Y2 = the same chain all-comb (masks 6666 / 9999). Vote in the LAB window gives the
      per-LE "FF used, q local" bits and the LAB clock bits.
  tree_{R8,E1,J15}: FFs at (38,31) N1 and (38,32) N1 clocked by that pin -> R8 clock tree.
usage: python3 tools/fuzz_vote2.py [solve]"""
import os, sys, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from fuzz_vote import FF, vote
LABS = [(20, 10), (30, 25), (12, 5)]


def design(tag):
    if tag.startswith("ff_"):
        _, x, y, kind = tag.split("_"); x, y = int(x), int(y)
        v = ["module top(input clk, input din, output dout);"]
        q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din", "set_location_assignment PIN_A15 -to dout"]
        prev = "din"
        for n in range(0, 32, 2):
            mask = {"X": "6666", "Y1": "6666", "Y2": "9999"}[kind]
            v.append(f"  wire c{n}; cycloneive_lcell_comb #(.lut_mask(16'h{mask})) l{n} (.dataa({prev}),.datab(din),.datac(1'b0),.datad(1'b0),.combout(c{n}));")
            q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l{n}")
            if kind == "X":
                v.append("  wire q%d; " % n + FF.format(n=f"r{n}", c="clk", d=f"c{n}", q=f"q{n}"))
                q.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{n}")
                prev = f"q{n}"
            else:
                prev = f"c{n}"
        if kind != "X":
            v[0] = "module top(input din, output dout);"; q = q[1:]
        v += [f"  assign dout = {prev};", "endmodule"]
    else:
        cpin = tag.split("_")[1]
        v = ["module top(input clk, input a, output y);", "  wire q1;",
             "  " + FF.format(n="r1", c="clk", d="a", q="q1"), "  " + FF.format(n="r2", c="clk", d="q1", q="y"), "endmodule"]
        q = [f"set_location_assignment PIN_{cpin} -to clk", "set_location_assignment PIN_M1 -to a", "set_location_assignment PIN_A15 -to y",
             "set_location_assignment FF_X38_Y31_N1 -to r1", "set_location_assignment FF_X38_Y32_N1 -to r2"]
    d = f"{R}/work/vt_{tag}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


TAGS = [f"ff_{x}_{y}_{k}" for x, y in LABS for k in ("X", "Y1", "Y2")] + ["tree_R8", "tree_E1", "tree_J15"]


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
        from rlabel import relbyte
        G = json.load(open(R + "/fuzz/lab_grid.json"))
        CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
        lin = lambda b, l: l * 294 + (295 - b)
        common = None
        for x, y in LABS:
            rel = {}
            for e in vote(f"ff_{x}_{y}_X", f"ff_{x}_{y}_Y1", f"ff_{x}_{y}_Y2"):
                if e[0] != "cram":
                    continue
                _, f, byte, bit, v = e
                df, db = f - CB[x], lin(byte, bit) - lin(*RW[y])
                if -14 <= df <= 25 and -8 <= db <= 80:
                    rel[(df, db)] = v
            print((x, y), "LAB-window vote bits", len(rel))
            common = rel if common is None else {k: v for k, v in common.items() if rel.get(k) == v}
        print("common to all LABs:", len(common))
        json.dump({"ff_q_local_all16": [[df, db, v] for (df, db), v in sorted(common.items())]}, open(R + "/fuzz/ff_vote.json", "w"), indent=0)
        t = vote("tree_R8", "tree_E1", "tree_J15")
        json.dump({"R8_to_38_31_32": t}, open(R + "/fuzz/clock_tree2.json", "w"), indent=0)
        print("tree2 bits", sum(e[0] == "cram" for e in t), "periph", sum(e[0] == "periph" for e in t))
    else:
        with cf.ThreadPoolExecutor(2) as ex:
            for tag, res in ex.map(run, TAGS):
                print(tag, res, flush=True)
