#!/usr/bin/env python3
"""Routing fuzz (Project X-Ray style tag solving).

Each specimen: K LUT+FF cells at random, pinned LEs in a small LAB region; every LUT
takes 4 random FF outputs. Quartus routes; quartus_sta lists the routing of every
reg->reg path. Output per specimen: top.rbf + pips.json (set of wire->wire hops).

usage: J=3 N=150 python3 tools/route_fuzz.py [region] ; region default 19:21,9:11
"""
import os, sys, re, json, random, subprocess, concurrent.futures as cf

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = os.environ.get("QUARTUS_BIN", os.path.expanduser("~/altera/13.1/quartus/bin"))
K = int(os.environ.get("K", "40"))

STA = """project_open top
create_timing_netlist
create_clock -name clk -period 20 [get_ports clk]
update_timing_netlist
report_timing -setup -from_clock clk -to_clock clk -npaths 20000 -pairs_only -detail full_path -show_routing -file paths.rpt
"""


def gen(d, seed, xs, ys):
    rnd = random.Random(seed)
    sites = [(x, y, n) for x in xs for y in ys for n in range(0, 32, 2)]
    sites = rnd.sample(sites, K)
    v = ["module top(input clk, input din, output dout);"]
    v.append(f"  wire [{K-1}:0] q;")
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_A15 -to dout"]
    for i, (x, y, n) in enumerate(sites):
        ins = rnd.sample([j for j in range(K) if j != i], 3)
        a = "din" if i == 0 else f"q[{rnd.randrange(K)}]"
        srcs = [a] + [f"q[{j}]" for j in ins]
        v.append(f"  wire w{i}; cycloneive_lcell_comb #(.lut_mask(16'h6996)) l{i} "
                 f"(.dataa({srcs[0]}),.datab({srcs[1]}),.datac({srcs[2]}),.datad({srcs[3]}),.combout(w{i}));")
        v.append(f"  dffeas r{i} (.clk(clk),.d(w{i}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),"
                 f".sload(1'b0),.asdata(1'b0),.q(q[{i}]));")
        q += [f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l{i}",
              f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{i}"]
    v += ["  assign dout = q[0];", "endmodule"]
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n")
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    json.dump(sites, open(d + "/sites.json", "w"))


ROW = re.compile(r"^;\s*[-\d.]+\s*;\s*[-\d.]+\s*;\s*\w*\s*;\s*(RE|IC|CELL)\s*;\s*\d+\s*;\s*(\S+)\s*;\s*(\S+)\s*;")


def parse(path):
    """Return the set of (from, to) hops seen on data paths."""
    pips, seq, in_data = set(), [], False
    for line in open(path, errors="ignore"):
        if "Data Arrival Path" in line:
            in_data, seq = True, []
            continue
        if "Data Required Path" in line:
            in_data = False
            continue
        if not in_data:
            continue
        m = ROW.match(line)
        if not m:
            continue
        kind, loc, what = m.groups()
        if kind == "CELL":
            seq = [loc + "." + what.split("|")[-1]] if "|" in what else [loc]
            continue
        node = loc + "." + what.split("|")[-1] if kind == "IC" else loc
        if seq and seq[-1] != node:
            pips.add((seq[-1], node))
        seq.append(node)
    return pips


def run(seed, xs, ys):
    d = f"{R}/work/rt_{seed:04d}"
    if not os.path.exists(d + "/pips.json"):
        gen(d, seed, xs, ys)
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        if r.returncode:
            return seed, "compile failed"
        open(d + "/sta.tcl", "w").write(STA)
        subprocess.run([Q + "/quartus_sta", "-t", "sta.tcl"], cwd=d, capture_output=True)
        if not os.path.exists(d + "/paths.rpt"):
            return seed, "sta failed"
        pips = parse(d + "/paths.rpt")
        json.dump(sorted(pips), open(d + "/pips.json", "w"))
        for junk in ("db", "incremental_db", "paths.rpt"):
            subprocess.run(["rm", "-rf", f"{d}/{junk}"])
    return seed, len(json.load(open(d + "/pips.json")))


if __name__ == "__main__":
    reg = sys.argv[1] if len(sys.argv) > 1 else "19:21,9:11"
    (x0, x1), (y0, y1) = [tuple(map(int, p.split(":"))) for p in reg.split(",")]
    xs, ys = range(x0, x1 + 1), range(y0, y1 + 1)
    s0, n = int(os.environ.get("SEED0", "0")), int(os.environ.get("N", "150"))
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "3"))) as ex:
        for seed, res in ex.map(lambda s: run(s, xs, ys), range(s0, s0 + n)):
            print(seed, res, flush=True)
