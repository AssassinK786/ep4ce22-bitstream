#!/usr/bin/env python3
"""Forced local-line hops via edited .rcf (clean-room: Quartus input/outputs only).

For LAB L and a pair (source LE_BUFFER I<m> of the LE at (sx, sy, n), line I<k> of L):
  X     : source FF q -> dest LUT L.N<d> datab (and -> pin B13); compiled normally, routing back-annotated
  Xf    : X re-fitted with its .rcf edited so the q -> dest branch is LE_BUFFER I<m> -> LOCAL_INTERCONNECT I<k>
  base  : same design with datab = 0
code(k, src) = diff(base, Xf) in L's window minus dest LUT / LUT-input-mux positions (LAB-relative).
Output: fuzz/force_<x>_<y>.json [{pair, src, legal, bits}]
usage: J=2 python3 tools/force_probe.py x y
"""
import os, sys, re, json, shutil, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import relbyte
Q = os.environ.get("QUARTUS_BIN", os.path.expanduser("~/altera/13.1/quartus/bin"))
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}
FF = "dffeas {n} (.clk(clk),.d({d}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({q}));"
X, Y = int(sys.argv[1]), int(sys.argv[2])
# (dy, m) -> k : own LAB (dy=0) and vertical links (dy = -1: source above, +1: source below), from the data
OWN = [(1, 15), (3, 15), (3, 30), (4, 1), (5, 17), (7, 31), (8, 3), (9, 18), (11, 32), (12, 5), (15, 33), (16, 34),
       (19, 10), (20, 35), (22, 25), (24, 36), (27, 13), (28, 37), (28, 29), (30, 29)]
PAIRS = [(0, m, k) for m, k in OWN] + [(1, 30, 15), (-1, 1, 29)]


def excl(d):
    e = {(SLOT[k][0], LEOFF[d] + ((1 - SLOT[k][1]) if (d // 2) % 2 else SLOT[k][1])) for k in SLOT}
    for p in "abcd":
        e |= {tuple(b) for b in LIM[f"N{d}.data{p}"]["bits"]}
    return e


def design(dirn, src, dslot, use):
    sx, sy, sn = src
    os.makedirs(dirn, exist_ok=True)
    v = ["module top(input clk, input din, input dt, output y, output yb);", "  wire c, q, w;",
         "  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
         "  " + FF.format(n="rs", d="c", q="q"),
         f"  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab({'q' if use else chr(49) + chr(39) + 'b0'}),.datac(1'b0),.datad(1'b0),.combout(w));",
         "  assign y = w;", "  assign yb = q;", "endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_T8 -to dt", "set_location_assignment PIN_A15 -to y", "set_location_assignment PIN_B13 -to yb",
         f"set_location_assignment LCCOMB_X{sx}_Y{sy}_N{sn} -to ls", f"set_location_assignment FF_X{sx}_Y{sy}_N{sn + 1} -to rs",
         f"set_location_assignment LCCOMB_X{X}_Y{Y}_N{dslot} -to ld"]
    open(dirn + "/top.v", "w").write("\n".join(v) + "\n"); open(dirn + "/extra.qsf", "w").write("\n".join(q) + "\n")


def compile_(dirn, keepdb=False):
    if not os.path.exists(dirn + "/top.rbf"):
        r = subprocess.run([R + "/tools/qcompile.sh", dirn], capture_output=True, text=True)
        if r.returncode:
            return False
    if keepdb and not os.path.exists(dirn + "/top.rcf"):
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=dirn, capture_output=True)
    if not keepdb:
        subprocess.run(["rm", "-rf", f"{dirn}/db", f"{dirn}/incremental_db", f"{dirn}/top.sof"])
    return True


def run(pair):
    dy, m, k = pair
    n = m - m % 2
    src = (X, Y + dy, n)
    dslot = 2 if (dy == 0 and n == 0) else 0
    tag = f"fp_{X}_{Y}_{dy}_{m}_{k}"
    dX, dB, dF = f"{R}/work/{tag}_X", f"{R}/work/{tag}_B", f"{R}/work/{tag}_F"
    design(dX, src, dslot, True); design(dB, src, dslot, False)
    if not (compile_(dX, keepdb=True) and compile_(dB)):
        return {"pair": pair, "legal": False, "why": "compile"}
    if not os.path.exists(dF + "/top.rbf"):
        shutil.rmtree(dF, ignore_errors=True); shutil.copytree(dX, dF)
        rcf = open(dF + "/top.rcf").read()
        blk = re.search(r"signal_name = rs \{(.*?)\n\}", rcf, re.S)
        body = blk.group(1)
        br = re.search(r"\n\t([^\n]*);\n\tdest = \( w, DATAB \)[^\n]*\n", body)      # first hop into w
        if not br:
            return {"pair": pair, "legal": False, "why": "no w branch"}
        lab = f"Label_FP_{m}"
        new_first = f"\n\tlabel = {lab}, LE_BUFFER:X{X}Y{Y + dy}S0I{m};\n\tLOCAL_INTERCONNECT:X{X}Y{Y}S0I{k};\n\tdest = ( w, DATAB ), route_port = DATAB;\n"
        rest = body[:br.start()] + body[br.end():]
        rest = re.sub(rf"\n\tLE_BUFFER:X{X}Y{Y + dy}S0I{m};", f"\n\tbranch_point = {lab};", rest)
        open(dF + "/top.rcf", "w").write(rcf.replace(body, new_first + rest.lstrip("\n")))
        r = subprocess.run([Q + "/quartus_fit", "top"], cwd=dF, capture_output=True, text=True)
        if "Error on line number" in r.stdout or r.returncode:
            subprocess.run(["rm", "-rf", f"{dF}/db", f"{dF}/incremental_db"])
            return {"pair": pair, "legal": False, "why": "rcf rejected"}
        subprocess.run([Q + "/quartus_asm", "top"], cwd=dF, capture_output=True)
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=dF, capture_output=True)
        subprocess.run(["rm", "-rf", f"{dF}/db", f"{dF}/incremental_db", f"{dF}/top.sof"])
    a, b = open(dB + "/top.rbf", "rb").read(), open(dF + "/top.rbf", "rb").read()
    hb, lane = RW[Y]; ex = excl(dslot); bits = []
    for df in range(-25, 26):
        f = CB[X] + df
        for db in range(0, 70):
            byte, ln = relbyte(hb, lane, db)
            o = F0 + FLEN * f + byte
            if (a[o] ^ b[o]) >> ln & 1 and (df, db) not in ex:
                bits.append([df, db, (b[o] >> ln) & 1])
    used = f"LOCAL_INTERCONNECT:X{X}Y{Y}S0I{k};" in open(dF + "/top.rcf").read()
    return {"pair": pair, "legal": used, "dest": dslot, "bits": bits}


if __name__ == "__main__":
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        res = list(ex.map(run, PAIRS))
    for r in res:
        print(r["pair"], r.get("legal"), r.get("why", ""), r.get("bits"), flush=True)
    json.dump(res, open(R + f"/fuzz/force_{X}_{Y}.json", "w"), indent=0)
