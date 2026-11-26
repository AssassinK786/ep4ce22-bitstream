#!/usr/bin/env python3
"""Sparse routing specimens: one toggling FF (src) -> one LUT input in another LAB (dst) -> FF -> pin.

Few routing hops per specimen, so each hop can be tied to its bits by intersection.
Specimens go to work/sp_<seed>/ (top.rbf, pips.json, sites.json). Baseline: work/sp_base.
usage: J=3 N=400 python3 tools/route_sparse.py
"""
import os, sys, json, random, subprocess, concurrent.futures as cf

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from route_fuzz import STA, parse, Q

LEG = {tuple(map(int, l.split())) for l in open(R + "/work/grid/legal.txt")}
LEG = {p for p in LEG if p[0] <= 41}          # stay inside the 1395-LAB part of the grid


def gen(d, seed):
    rnd = random.Random(seed)
    while True:
        sx, sy = rnd.randrange(8, 33), rnd.randrange(4, 28)
        dx, dy = sx + rnd.randint(-5, 5), sy + rnd.randint(-5, 5)
        if (sx, sy) in LEG and (dx, dy) in LEG and (sx, sy) != (dx, dy):
            break
    sn, dn = rnd.randrange(0, 32, 2), rnd.randrange(0, 32, 2)
    port = rnd.choice("abcd")
    ins = {p: "1'b0" for p in "abcd"}
    ins[port] = "q0"
    v = f"""module top(input clk, output dout);
  wire q0, q1, w0, w1;
  cycloneive_lcell_comb #(.lut_mask(16'h5555)) l0 (.dataa(q0),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(w0));
  dffeas r0 (.clk(clk),.d(w0),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(q0));
  cycloneive_lcell_comb #(.lut_mask(16'h{ {'a':'aaaa','b':'cccc','c':'f0f0','d':'ff00'}[port] })) l1 (.dataa({ins['a']}),.datab({ins['b']}),.datac({ins['c']}),.datad({ins['d']}),.combout(w1));
  dffeas r1 (.clk(clk),.d(w1),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(q1));
  assign dout = q1;
endmodule
"""
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to dout",
         f"set_location_assignment LCCOMB_X{sx}_Y{sy}_N{sn} -to l0", f"set_location_assignment FF_X{sx}_Y{sy}_N{sn+1} -to r0",
         f"set_location_assignment LCCOMB_X{dx}_Y{dy}_N{dn} -to l1", f"set_location_assignment FF_X{dx}_Y{dy}_N{dn+1} -to r1"]
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write(v)
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    json.dump([[sx, sy, sn], [dx, dy, dn]], open(d + "/sites.json", "w"))


def run(seed):
    d = f"{R}/work/sp_{seed:04d}"
    if os.path.exists(d + "/pips.json"):
        return seed, "cached"
    gen(d, seed)
    r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
    if r.returncode:
        return seed, "compile failed"
    open(d + "/sta.tcl", "w").write(STA.replace("-from_clock clk -to_clock clk ", ""))
    subprocess.run([Q + "/quartus_sta", "-t", "sta.tcl"], cwd=d, capture_output=True)
    if not os.path.exists(d + "/paths.rpt"):
        return seed, "sta failed"
    pips = parse(d + "/paths.rpt")
    # clock path hops too: parse the whole report, not only data arrival
    json.dump(sorted(pips), open(d + "/pips.json", "w"))
    subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db"])
    return seed, len(pips)


if __name__ == "__main__":
    s0, n = int(os.environ.get("SEED0", "0")), int(os.environ.get("N", "400"))
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "3"))) as ex:
        for seed, res in ex.map(run, range(s0, s0 + n)):
            print(seed, res, flush=True)
