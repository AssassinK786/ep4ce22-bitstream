#!/usr/bin/env python3
"""Forced local-line hops, single-branch nets (clean-room: Quartus .rcf in/out only).

Design: source FF at (sx, sy, n) (fed by its own LUT from pin M1) drives ONLY the dest LUT L.N<d> datab;
dest output -> pin A15. The source net therefore has one branch in the .rcf.
  X  : compiled normally, routing back-annotated
  Xf : X re-fitted with the source net's block replaced by  LE_BUFFER:<src LAB>I<m>; LOCAL_INTERCONNECT:<L>I<k>;
code(k, src) = positions in L's window that are 1 in Xf and 0 in X, outside the dest LUT / LUT-input-mux
positions (LAB-relative). Source-side changes (frames 8 / 9 / 11 near the source LE) are kept in "src_bits".
Pairs: every own LE_BUFFER m (0..31) with every line k in its candidate set, and vertical buffers.
Output: fuzz/force2_<x>_<y>.json
usage: J=2 python3 tools/force2_probe.py x y
"""
import os, sys, re, json, shutil, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN
from rlabel import relbyte
from force_probe import excl, LEOFF, CB, RW, FF, Q
X, Y = int(sys.argv[1]), int(sys.argv[2])
# candidate lines per own buffer (union of what the data / earlier probes saw); vertical links
OWNC = {0: [15, 30], 1: [15, 30], 2: [1, 17], 3: [15, 30], 4: [1, 17], 5: [1, 17], 6: [31, 3], 7: [31, 3],
        8: [3, 18], 9: [18, 3], 10: [32, 5], 11: [32, 5], 12: [5, 32], 13: [5, 32], 14: [33, 7], 15: [33, 7],
        16: [34, 8], 17: [34, 8], 18: [10, 35], 19: [10, 35], 20: [35, 10], 21: [35, 10], 22: [25, 11],
        23: [25, 11], 24: [36, 12], 25: [36, 12], 26: [13, 37], 27: [13, 37], 28: [37, 29], 29: [29, 37],
        30: [29, 14], 31: [29, 14]}
PAIRS = [(0, m, k) for m, ks in OWNC.items() for k in ks]
PAIRS += [(1, m, k) for m in (28, 29, 30, 31) for k in (15, 14, 29)] + [(-1, m, k) for m in (0, 1, 2, 3) for k in (29, 15, 0)]


def design(dirn, src, dslot):
    sx, sy, sn = src
    os.makedirs(dirn, exist_ok=True)
    v = ["module top(input clk, input din, input dt, output y);", "  wire c, q, w;",
         "  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
         "  " + FF.format(n="rs", d="c", q="q"),
         "  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab(q),.datac(1'b0),.datad(1'b0),.combout(w));",
         "  assign y = w;", "endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_T8 -to dt", "set_location_assignment PIN_A15 -to y",
         f"set_location_assignment LCCOMB_X{sx}_Y{sy}_N{sn} -to ls", f"set_location_assignment FF_X{sx}_Y{sy}_N{sn + 1} -to rs",
         f"set_location_assignment LCCOMB_X{X}_Y{Y}_N{dslot} -to ld"]
    open(dirn + "/top.v", "w").write("\n".join(v) + "\n"); open(dirn + "/extra.qsf", "w").write("\n".join(q) + "\n")


def base_for(src, dslot):
    tag = f"f2_{X}_{Y}_{src[0]}_{src[1]}_{src[2]}_d{dslot}_X"
    d = f"{R}/work/{tag}"
    if not os.path.exists(d + "/top.rcf"):
        design(d, src, dslot)
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        if r.returncode:
            return None
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=d, capture_output=True)
    return d


def run(pair):
    dy, m, k = pair
    n = m - m % 2
    src = (X, Y + dy, n)
    dslot = 2 if (dy == 0 and n == 0) else 0
    dX = base_for(src, dslot)
    if not dX:
        return {"pair": pair, "legal": False, "why": "compile"}
    dF = f"{R}/work/f2_{X}_{Y}_{dy}_{m}_{k}_F"
    if not os.path.exists(dF + "/result.json"):
        shutil.rmtree(dF, ignore_errors=True); shutil.copytree(dX, dF)
        rcf = open(dF + "/top.rcf").read()
        blk = re.search(r"signal_name = rs \{.*?\n\}", rcf, re.S)
        dest = "dest = ( w, DATAB );"          # no route_port: the fitter picks the physical input
        new = (f"signal_name = rs {{\n\tLE_BUFFER:X{X}Y{Y + dy}S0I{m};\n\tLOCAL_INTERCONNECT:X{X}Y{Y}S0I{k};\n\t{dest}\n}}")
        open(dF + "/top.rcf", "w").write(rcf.replace(blk.group(0), new))
        r = subprocess.run([Q + "/quartus_fit", "top"], cwd=dF, capture_output=True, text=True)
        ok = "Error on line number" not in r.stdout and r.returncode == 0
        res = {"pair": pair, "legal": ok}
        if ok:
            subprocess.run([Q + "/quartus_asm", "top"], cwd=dF, capture_output=True)
            subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=dF, capture_output=True)
            ok = f"LOCAL_INTERCONNECT:X{X}Y{Y}S0I{k};" in open(dF + "/top.rcf").read()
            res["legal"] = ok
        if ok:
            a, b = open(dX + "/top.rbf", "rb").read(), open(dF + "/top.rbf", "rb").read()
            hb, lane = RW[Y]; ex = excl(dslot); code, srcb = [], []
            for df in range(-25, 26):
                f = CB[X] + df
                for db in range(0, 70):
                    byte, ln = relbyte(hb, lane, db)
                    o = F0 + FLEN * f + byte
                    if (a[o] ^ b[o]) >> ln & 1 and (df, db) not in ex:
                        v = (b[o] >> ln) & 1
                        (srcb if df in (8, 9, 11, -1) else code).append([df, db, v])
            res.update({"bits": code, "src_bits": srcb, "dest": dslot})
        json.dump(res, open(dF + "/result.json", "w"))
        for sub in ("db", "incremental_db"):
            shutil.rmtree(f"{dF}/{sub}", ignore_errors=True)
    return json.load(open(dF + "/result.json"))


if __name__ == "__main__":
    # bases first (one per source / dest slot), then the forced fits
    srcs = sorted({((X, Y + dy, m - m % 2), 2 if (dy == 0 and m - m % 2 == 0) else 0) for dy, m, k in PAIRS})
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        list(ex.map(lambda s: base_for(*s), srcs))
        res = list(ex.map(run, PAIRS))
    for r in res:
        if r.get("legal"):
            print(r["pair"], "code", [b for b in r["bits"] if b[2] == 1], "src", r["src_bits"], flush=True)
    print("legal", sum(1 for r in res if r.get("legal")), "of", len(res))
    json.dump(res, open(R + f"/fuzz/force2_{X}_{Y}.json", "w"), indent=0)
