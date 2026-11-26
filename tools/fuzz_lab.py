#!/usr/bin/env python3
"""LAB-internal fuzz: FF/output-select bits per LE and LOCAL_LINE (feedback) codes.

Each specimen fills one LAB with a 16-LE chain. Every LE gets a config:
  comb - LUT only, its combout used by a later LE (or the pin)
  reg  - LUT -> own FF, only the FF output used
  both - combout used by a later LE and the FF output used
LUT inputs come from earlier combouts or any FF output in the LAB (no comb loops).
~15 % of specimens use no FFs at all (LAB-level clock bits).
Outputs per specimen in work/lb_<seed>/: top.rbf, pips.json (STA hops), cfg.json.
usage: J=2 N=70 python3 tools/fuzz_lab.py
"""
import os, sys, json, random, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from route_fuzz import STA, parse, Q

LABS = [(20, 10), (5, 22), (30, 25), (38, 32), (12, 5), (25, 30), (38, 30)]


def gen(d, seed):
    rnd = random.Random(seed)
    x, y = rnd.choice(LABS)
    nofl = rnd.random() < 0.15
    order = list(range(0, 32, 2))
    rnd.shuffle(order)
    cfg = {}
    v = ["module top(input clk, input din, output dout);"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_A15 -to dout"]
    comb_srcs, reg_srcs = ["din"], []
    pending_q = []
    for i, n in enumerate(order):
        c = "comb" if nofl else rnd.choice(["comb", "reg", "both"])
        cfg[n] = c
        pool = comb_srcs + reg_srcs
        a = comb_srcs[-1] if i else "din"
        others = [rnd.choice(pool) for _ in range(3)]
        if i and cfg[order[i - 1]] in ("reg", "both"):
            others[0] = f"q{order[i - 1]}"     # every FF output is read by the next LE
        ins = [a] + others
        v.append(f"  wire c{n}; cycloneive_lcell_comb #(.lut_mask(16'h6996)) l{n} "
                 f"(.dataa({ins[0]}),.datab({ins[1]}),.datac({ins[2]}),.datad({ins[3]}),.combout(c{n}));")
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l{n}")
        if c in ("reg", "both"):
            v.append(f"  wire q{n}; dffeas r{n} (.clk(clk),.d(c{n}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),"
                     f".sload(1'b0),.asdata(1'b0),.q(q{n}));")
            q.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{n}")
            reg_srcs.append(f"q{n}")
            pending_q.append(f"q{n}")
        if c in ("comb", "both"):
            comb_srcs.append(f"c{n}")
    # every FF output and the last combout must be observed: XOR them into dout through
    # the chain (later LEs read them); leftovers are folded at the pin by one extra LUT
    # outside the LAB (a free LE in the LAB below is avoided: use a LAB 2 rows away)
    last = comb_srcs[-1]
    leftovers = [pending_q[-1]] if pending_q and cfg[order[-1]] in ("reg", "both") else []
    if leftovers:
        ins = ([last] + leftovers + ["1'b0"] * 3)[:4]
        v.append(f"  wire fo; cycloneive_lcell_comb #(.lut_mask(16'h6996)) lfo "
                 f"(.dataa({ins[0]}),.datab({ins[1]}),.datac({ins[2]}),.datad({ins[3]}),.combout(fo));")
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y + 2 if y < 30 else y - 2}_N0 -to lfo")
        last = "fo"
    v += [f"  assign dout = {last};", "endmodule"]
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n")
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    json.dump({"lab": [x, y], "cfg": cfg, "nofl": nofl}, open(d + "/cfg.json", "w"))


def run(seed):
    d = f"{R}/work/lb_{seed:04d}"
    if os.path.exists(d + "/pips.json"):
        return seed, "cached"
    gen(d, seed)
    r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
    if r.returncode:
        return seed, "compile failed: " + (r.stdout + r.stderr)[-300:].replace("\n", " ")
    open(d + "/sta.tcl", "w").write(STA.replace("-from_clock clk -to_clock clk ", ""))
    subprocess.run([Q + "/quartus_sta", "-t", "sta.tcl"], cwd=d, capture_output=True)
    pips = parse(d + "/paths.rpt") if os.path.exists(d + "/paths.rpt") else set()
    json.dump(sorted(pips), open(d + "/pips.json", "w"))
    subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/paths.rpt", f"{d}/top.sof"])
    return seed, len(pips)


if __name__ == "__main__":
    s0, n = int(os.environ.get("SEED0", "0")), int(os.environ.get("N", "70"))
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        for seed, res in ex.map(run, range(s0, s0 + n)):
            print(seed, res, flush=True)
