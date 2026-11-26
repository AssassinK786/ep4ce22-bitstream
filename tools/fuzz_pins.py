#!/usr/bin/env python3
"""Per-pin I/O bits for the DE0-Nano user pins.

Outputs (LEDs) A15 A13 B13 A11 D1 F3 B1 L3: each driven by its own FF.
Inputs KEY0 J15, KEY1 E1, DIP M1 T8 B9 M15: each read by its own FF. R8: the clock.
Designs (work/pn_<tag>/):
  allA, allB      - every pin used; drivers/readers in LAB set A or B (different LABs)
  minusA_<pin>    - as allA without that pin (its FF and the pin removed)
  minusB_<pin>    - as allB without that pin
Pin k's I/O bits = (allA ^ minusA_k) & (allB ^ minusB_k) [same value in both], with the
route bits being the remainder. The CRAM and the x4 periphery block are both diffed.
usage: J=2 python3 tools/fuzz_pins.py
"""
import os, sys, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTS = ["A15", "A13", "B13", "A11", "D1", "F3", "B1", "L3"]
INS = ["J15", "E1", "M1", "T8", "B9", "M15"]
# LAB sets: A near the pins' edges, B a few columns/rows in
LABA = [(38, 32), (40, 30), (36, 33), (30, 33), (3, 30), (8, 30), (38, 31), (2, 25),
        (36, 20), (3, 22), (20, 3), (30, 3), (36, 10), (25, 20)]
LABB = [(32, 28), (34, 25), (31, 29), (26, 29), (8, 26), (12, 26), (10, 29), (7, 22),
        (31, 16), (8, 16), (20, 8), (30, 8), (31, 12), (20, 18)]


def gen(tag, labs, drop=None):
    d = f"{R}/work/pn_{tag}"
    os.makedirs(d, exist_ok=True)
    v = ["module top(input clk, " + ", ".join(f"input i_{p}" for p in INS if p != drop) +
         (", " if [p for p in OUTS if p != drop] else "") + ", ".join(f"output o_{p}" for p in OUTS if p != drop) + ");"]
    q = ["set_location_assignment PIN_R8 -to clk"]
    k = 0
    ins_used = [p for p in INS if p != drop]
    # input readers: FF r_<pin> <= pin ; their outputs XORed into the first output driver
    for p in INS:
        x, y = labs[k]; k += 1
        if p == drop:
            continue
        q.append(f"set_location_assignment PIN_{p} -to i_{p}")
        v.append(f"  wire q_{p}; dffeas r_{p} (.clk(clk),.d(i_{p}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(q_{p}));")
        q.append(f"set_location_assignment FF_X{x}_Y{y}_N1 -to r_{p}")
    srcs = [f"q_{p}" for p in ins_used] or ["1'b0"]
    for j, p in enumerate(OUTS):
        x, y = labs[len(INS) + j]
        if p == drop:
            continue
        a = srcs[j % len(srcs)]
        b = srcs[(j + 1) % len(srcs)]
        v.append(f"  wire c_{p}, f_{p}; cycloneive_lcell_comb #(.lut_mask(16'h6666)) l_{p} (.dataa({a}),.datab({b}),.datac(1'b0),.datad(1'b0),.combout(c_{p}));")
        v.append(f"  dffeas d_{p} (.clk(clk),.d(c_{p}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(f_{p}));")
        v.append(f"  assign o_{p} = f_{p};")
        q.append(f"set_location_assignment PIN_{p} -to o_{p}")
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{2 * j + 2} -to l_{p}")
        q.append(f"set_location_assignment FF_X{x}_Y{y}_N{2 * j + 3} -to d_{p}")
    v.append("endmodule")
    open(d + "/top.v", "w").write("\n".join(v) + "\n")
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


def run(job):
    tag, labs, drop = job
    d = gen(tag, labs, drop)
    if not os.path.exists(d + "/top.rbf"):
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
        if r.returncode:
            return tag, "FAIL " + (r.stdout + r.stderr)[-300:].replace("\n", " ")
    return tag, "ok"


if __name__ == "__main__":
    jobs = [("allA", LABA, None), ("allB", LABB, None)]
    for p in OUTS + INS:
        jobs += [(f"minusA_{p}", LABA, p), (f"minusB_{p}", LABB, p)]
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        for tag, res in ex.map(run, jobs):
            print(tag, res, flush=True)
