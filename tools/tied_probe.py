#!/usr/bin/env python3
"""Code of a natural (line, source) hop: force2 base design X (source -> L.N<d>.datab) vs the same design
with datab tied to 0 (source LE kept alive by a pin). Element-plane positions (all LUT / LUT-input-mux
positions, frames -1, 8, 9, 11) are excluded; the rest of L's window that turns on in X is the code.
usage: python3 tools/tied_probe.py  -> appends fuzz/tied.json"""
import os, sys, re, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import relbyte
sys.argv = [sys.argv[0], "0", "0"]
from force_probe import LEOFF, CB, RW, FF, Q, SLOT, LIM
EXC = {(SLOT[k][0], LEOFF[n] + ((1 - SLOT[k][1]) if (n // 2) % 2 else SLOT[k][1])) for n in LEOFF for k in SLOT}
EXC |= {tuple(b) for e in LIM.values() for b in e["bits"]}
CASES = [((x, y), (x, y + 1, 30), 0) for x, y in ((20, 10), (30, 25), (12, 5))] + [((x, y), (x, y - 1, 0), 0) for x, y in ((20, 10), (30, 25), (12, 6))]


def tied(lab, src, d):
    x, y = lab; sx, sy, sn = src
    dX = f"{R}/work/f2_{x}_{y}_{sx}_{sy}_{sn}_d{d}_X"
    if not os.path.exists(dX + "/top.rcf"):
        import subprocess as _sp
        _sp.run([sys.executable, R + "/tools/force2_probe.py", str(x), str(y)], capture_output=True) if False else None
        from force2_probe import base_for as _bf
        _bf((sx, sy, sn), d)
    dT = f"{R}/work/tied_{x}_{y}_{sx}_{sy}_{sn}_d{d}"
    os.makedirs(dT, exist_ok=True)
    v = ["module top(input clk, input din, input dt, output y, output yb);", "  wire c, q, w;",
         "  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
         "  " + FF.format(n="rs", d="c", q="q"),
         "  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(w));",
         "  assign y = w;", "  assign yb = q;", "endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din", "set_location_assignment PIN_T8 -to dt",
         "set_location_assignment PIN_A15 -to y", "set_location_assignment PIN_B13 -to yb",
         f"set_location_assignment LCCOMB_X{sx}_Y{sy}_N{sn} -to ls", f"set_location_assignment FF_X{sx}_Y{sy}_N{sn + 1} -to rs",
         f"set_location_assignment LCCOMB_X{x}_Y{y}_N{d} -to ld"]
    open(dT + "/top.v", "w").write("\n".join(v) + "\n"); open(dT + "/extra.qsf", "w").write("\n".join(q) + "\n")
    if not os.path.exists(dT + "/top.rbf"):
        subprocess.run([R + "/tools/qcompile.sh", dT], capture_output=True)
        subprocess.run(["rm", "-rf", f"{dT}/db", f"{dT}/incremental_db"])
    blk = re.search(r"signal_name = rs \{(.*?)\n\}", open(dX + "/top.rcf").read(), re.S).group(1)
    el = re.findall(r"(\w+):X(\d+)Y(\d+)S0I(\d+);", blk)
    hops = [(int(e[3]), el[i - 1]) for i, e in enumerate(el) if e[0] == "LOCAL_INTERCONNECT" and (int(e[1]), int(e[2])) == (x, y) and i]
    a, b = open(dT + "/top.rbf", "rb").read(), open(dX + "/top.rbf", "rb").read()
    hb, lane = RW[y]; on = []
    for df in range(-25, 26):
        for db in range(-12, 83):
            if (df, db + 70) in EXC or (df, db - 70) in EXC:    # element positions of the rows above / below
                continue
            byte, ln = relbyte(hb, lane, db)
            o = F0 + FLEN * (CB[x] + df) + byte
            if (a[o] ^ b[o]) >> ln & 1 and (b[o] >> ln) & 1 and (df, db) not in EXC and df not in (-1, 8, 9, 11):
                on.append([df, db, 1])
    if not hops:
        return {"lab": lab, "key": None, "hops": [], "bits": on}
    k0, (kind, sx_, sy_, si) = hops[0]
    dx_, dy_ = int(sx_) - x, int(sy_) - y
    key = f"{k0}|{kind}_I{si}" if (dx_, dy_) == (0, 0) else f"{k0}|{kind}@{dx_},{dy_}_I{si}"
    return {"lab": lab, "key": key, "hops": hops, "bits": on}


with cf.ThreadPoolExecutor(2) as ex:
    res = list(ex.map(lambda c: tied(*c), CASES))
for r in res:
    print(r["lab"], r["key"], r["bits"])
json.dump(res, open(R + "/fuzz/tied.json", "w"), indent=0)
