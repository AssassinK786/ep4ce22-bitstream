#!/usr/bin/env python3
"""Forced routing chains via .rcf (clean-room: Quartus in/out only). Generalises force2_probe.py.

A chain is a list of hops relative to the destination LAB L = (x, y):
  [("LE_BUFFER", dx, dy, m), ("R4"|"C4"|"R24"|"C16", dx, dy, i), ..., ("LOCAL_INTERCONNECT", 0, 0, k)]
The source FF sits in the LE that owns LE_BUFFER m of LAB (x+dx, y+dy) (LE n = m - m % 2) and drives ONLY
L.N<d>.datab (d = 0, or 2 when the source is L.N0). X = natural build; Xf = X re-fitted with the source
net's .rcf block replaced by the chain. Recorded: every CRAM bit that differs, relative to L
(df = frame - colbase(x), db = row-linear byte offset from L's high byte, lane folded in), within
frames -25..+40 of L's column and row bytes -150..+220, excluding L's dest LUT / LUT-input-mux
positions. Bits turning on = the chain's code; bits turning off = the natural route's code.
usage: python3 tools/force3_probe.py <chains.json> ; writes fuzz/force3_<name>.json
"""
import os, sys, re, json, shutil, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
sys.argv_save = list(sys.argv); sys.argv = [sys.argv[0], "0", "0"]
from force_probe import excl, CB, RW, FF, Q
sys.argv = sys.argv_save
LIN = lambda byte, lane: lane * 295 + (295 - byte)


def design(dirn, L, src, d):
    x, y = L; sx, sy, sn = src
    os.makedirs(dirn, exist_ok=True)
    v = ["module top(input clk, input din, input dt, output y);", "  wire c, q, w;",
         "  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
         "  " + FF.format(n="rs", d="c", q="q"),
         "  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab(q),.datac(1'b0),.datad(1'b0),.combout(w));",
         "  assign y = w;", "endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_T8 -to dt", "set_location_assignment PIN_A15 -to y",
         f"set_location_assignment LCCOMB_X{sx}_Y{sy}_N{sn} -to ls", f"set_location_assignment FF_X{sx}_Y{sy}_N{sn + 1} -to rs",
         f"set_location_assignment LCCOMB_X{x}_Y{y}_N{d} -to ld"]
    open(dirn + "/top.v", "w").write("\n".join(v) + "\n"); open(dirn + "/extra.qsf", "w").write("\n".join(q) + "\n")


def rel_diff(a, b, L, d):
    x, y = L
    hb, lane = RW[y]; base = LIN(hb, lane); ex = excl(d); out = []
    for f in range(CB[x] - 25, CB[x] + 41):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            xo = a[o + byte] ^ b[o + byte]
            if not xo:
                continue
            for bit in range(8):
                if xo >> bit & 1:
                    df, db = f - CB[x], LIN(byte, bit) - base
                    if -150 <= db <= 220 and (df, db) not in ex:
                        out.append([df, db, (b[o + byte] >> bit) & 1])
    return out


def run(job):
    name, L, chain = job
    x, y = L
    kind0, dx, dy, m = chain[0]
    n = m - m % 2
    src = (x + dx, y + dy, n)
    d = 2 if (dx, dy) == (0, 0) and n == 0 else 0
    tag = f"f3_{x}_{y}_" + "_".join(f"{h[0]}{h[1]}{h[2]}{h[3]}" for h in chain).replace("-", "m")
    dX, dF = f"{R}/work/{tag}_X", f"{R}/work/{tag}_F"
    if os.path.exists(dF + "/result.json"):
        return json.load(open(dF + "/result.json"))
    if not os.path.exists(dX + "/top.rcf"):
        design(dX, L, src, d)
        if subprocess.run([R + "/tools/qcompile.sh", dX], capture_output=True).returncode:
            return {"name": name, "L": L, "chain": chain, "legal": False, "why": "compile"}
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=dX, capture_output=True)
    shutil.rmtree(dF, ignore_errors=True); shutil.copytree(dX, dF)
    rcf = open(dF + "/top.rcf").read()
    blk = re.search(r"signal_name = rs \{.*?\n\}", rcf, re.S).group(0)
    els = "".join(f"\t{h[0]}:X{x + h[1]}Y{y + h[2]}S0I{h[3]};\n" for h in chain)
    open(dF + "/top.rcf", "w").write(rcf.replace(blk, "signal_name = rs {\n" + els + "\tdest = ( w, DATAB );\n}"))
    r = subprocess.run([Q + "/quartus_fit", "top"], cwd=dF, capture_output=True, text=True)
    res = {"name": name, "L": L, "chain": chain, "legal": "Error on line number" not in r.stdout and r.returncode == 0}
    if res["legal"]:
        subprocess.run([Q + "/quartus_asm", "top"], cwd=dF, capture_output=True)
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=dF, capture_output=True)
        txt = open(dF + "/top.rcf").read()
        res["legal"] = all(f"{h[0]}:X{x + h[1]}Y{y + h[2]}S0I{h[3]};" in txt for h in chain)
    if res["legal"]:
        res["bits"] = rel_diff(open(dX + "/top.rbf", "rb").read(), open(dF + "/top.rbf", "rb").read(), L, d)
        nat = re.search(r"signal_name = rs \{(.*?)\n\}", open(dX + "/top.rcf").read(), re.S).group(1)
        res["natural"] = re.findall(r"(\w+):X(\d+)Y(\d+)S0I(\d+);", nat)
    json.dump(res, open(dF + "/result.json", "w"))
    for sub in ("db", "incremental_db"):
        shutil.rmtree(f"{dF}/{sub}", ignore_errors=True)
    return res


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    name = os.path.basename(sys.argv[1]).rsplit(".", 1)[0]
    jobs = [(c["name"], tuple(L), [tuple(h) for h in c["chain"]]) for c in spec for L in c["labs"]]
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        res = list(ex.map(run, jobs))
    for r in res:
        print(r["name"], r["L"], "legal" if r.get("legal") else "illegal " + r.get("why", ""),
              [b for b in r.get("bits", []) if b[2] == 1][:12], flush=True)
    json.dump(res, open(R + f"/fuzz/force3_{name}.json", "w"), indent=0)
