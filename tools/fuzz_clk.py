#!/usr/bin/env python3
"""Clock chain from R8 to a LAB: pairs per LAB L.
  ck_<x>_<y>   M1 -> FF at L (N1, clocked by R8) -> A15
  nc_<x>_<y>   M1 -> LUT at L (N0, buffer) -> A15  (no clock anywhere)
diff(ck, nc) = clock chain + LAB clock + FF bits (+ a little routing difference).
usage: J=2 python3 tools/fuzz_clk.py
"""
import os, sys, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABS = [(38, 31), (38, 32), (38, 33), (38, 30), (20, 10), (5, 22), (30, 25), (12, 5), (25, 30),
        (3, 30), (36, 10), (20, 18)]


def gen(tag, x, y, clocked):
    d = f"{R}/work/{tag}"
    os.makedirs(d, exist_ok=True)
    if clocked:
        v = ("module top(input clk, input a, output y);\n"
             "  dffeas r (.clk(clk),.d(a),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(y));\n"
             "endmodule\n")
        q = f"set_location_assignment PIN_R8 -to clk\nset_location_assignment FF_X{x}_Y{y}_N1 -to r\n"
    else:
        v = ("module top(input a, output y);\n"
             "  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) l (.dataa(a),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(y));\n"
             "endmodule\n")
        q = f"set_location_assignment LCCOMB_X{x}_Y{y}_N0 -to l\n"
    q += "set_location_assignment PIN_M1 -to a\nset_location_assignment PIN_A15 -to y\n"
    open(d + "/top.v", "w").write(v)
    open(d + "/extra.qsf", "w").write(q)
    return d


def run(job):
    tag, x, y, c = job
    d = gen(tag, x, y, c)
    if not os.path.exists(d + "/top.rbf"):
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
        if r.returncode:
            return tag, "FAIL " + (r.stdout + r.stderr)[-200:].replace("\n", " ")
    return tag, "ok"


if __name__ == "__main__":
    jobs = [(f"ck_{x}_{y}", x, y, True) for x, y in LABS] + [(f"nc_{x}_{y}", x, y, False) for x, y in LABS]
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        for tag, res in ex.map(run, jobs):
            print(tag, res, flush=True)
