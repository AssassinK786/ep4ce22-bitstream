#!/usr/bin/env python3
"""Local-line source sweep with complete routing labels from the .rcf (clean-room: Quartus in/out only).

For a test LAB L = (x, y): one net per design, from a source FF at position S to the dest LUT L.N0 datab.
  X_S   : M1 -> LUT(S) -> FF(S) ; q -> pin B13 and -> L.N0.datab ; L.N0 dataa = pin T8 ; L.N0 -> pin A15
  base0 : same, with L.N0.datab = 0 (the source still drives B13)
Diff(X_S, base0) inside L's window (frames -25..25, LAB-relative bytes 0..69), minus L.N0's LUT-content and
LUT-input-mux positions, are the bits that route the net into L: the code of the (line, source) that
X_S's .rcf shows for the hop into LOCAL_INTERCONNECT:L (plus R4/C4 hops ending in L, recorded too).
Sources: every LE of L itself, of the LABs left/right/above/below, and LEs 2..5 LABs away (R4/C4).
Output: fuzz/src_sweep_<x>_<y>.json [{src, hops (in L), line, source label, bits [[df,db,v]...]}]
usage: J=2 python3 tools/src_sweep.py x y
"""
import os, sys, re, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES
from rlabel import relbyte
Q = os.environ.get("QUARTUS_BIN", os.path.expanduser("~/altera/13.1/quartus/bin"))
G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}; RW = {int(k): tuple(v) for k, v in G["row"].items()}
LEG = {tuple(map(int, l.split())) for l in open(R + "/work/grid/legal.txt")}
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
FF = "dffeas {n} (.clk(clk),.d({d}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({q}));"
X, Y = int(sys.argv[1]), int(sys.argv[2])
lin = lambda b, l: l * 295 + (295 - b)
EXCL = {(SLOT[k][0], SLOT[k][1]) for k in SLOT}            # N0 LUT content (LEOFF 0)
EXCL |= {tuple(p) for key in ("N0.dataa", "N0.datab", "N0.datac", "N0.datad") for p in LIM[key]["bits"]}


def sources():
    out = []
    for dx, dy in [(0, 0), (-1, 0), (1, 0)]:
        for n in range(0, 32, 2):
            if (dx, dy) == (0, 0) and n == 0:
                continue
            out.append((X + dx, Y + dy, n))
    for dx, dy in [(0, 1), (0, -1), (2, 0), (-3, 0), (0, 3), (0, -4), (5, 0), (-5, 0)]:
        for n in (10,):
            out.append((X + dx, Y + dy, n))
    return [s for s in out if (s[0], s[1]) in LEG and s[0] <= 41]


def design(tag, s):
    d = f"{R}/work/sw_{X}_{Y}_{tag}"
    os.makedirs(d, exist_ok=True)
    sx, sy, sn = s
    use = not tag.startswith("b_")
    v = ["module top(input clk, input din, input dt, output y, output yb);", "  wire c, q, w;",
         f"  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
         "  " + FF.format(n="rs", d="c", q="q"),
         f"  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab({'q' if use else '1' + chr(39) + 'b0'}),.datac(1'b0),.datad(1'b0),.combout(w));",
         "  assign y = w;", "  assign yb = q;", "endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_T8 -to dt", "set_location_assignment PIN_A15 -to y", "set_location_assignment PIN_B13 -to yb",
         f"set_location_assignment LCCOMB_X{sx}_Y{sy}_N{sn} -to ls", f"set_location_assignment FF_X{sx}_Y{sy}_N{sn + 1} -to rs",
         f"set_location_assignment LCCOMB_X{X}_Y{Y}_N0 -to ld"]
    open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


def build(tag, s):
    d = design(tag, s)
    if not os.path.exists(d + "/top.rcf"):
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        if r.returncode:
            return None
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=d, capture_output=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
    return d


def window_bits(a, b):
    """LAB-relative positions in L's window where a and b differ, with b's value."""
    hb, lane = RW[Y]
    out = {}
    for df in range(-25, 26):
        f = CB[X] + df
        for db in range(0, 70):
            byte, ln = relbyte(hb, lane, db)
            o = F0 + FLEN * f + byte
            if (a[o] ^ b[o]) >> ln & 1 and (df, db) not in EXCL:
                out[(df, db)] = (b[o] >> ln) & 1
    return out


def hops_into_L(rcf):
    """(line, previous element) for hops into LOCAL_INTERCONNECT of L, from the q net's block."""
    hops = []
    lines = rcf.splitlines()
    for i, l in enumerate(lines):
        m = re.search(rf"LOCAL_INTERCONNECT:X{X}Y{Y}S0I(\d+);", l)
        if m:
            prev = re.search(r"(\w+):X(\d+)Y(\d+)S(\d+)I(\d+);", lines[i - 1]) if i else None
            p = f"{prev[1]}@{int(prev[2]) - X},{int(prev[3]) - Y}_I{prev[5]}" if prev else "?"
            hops.append((int(m[1]), p))
    return hops


if __name__ == "__main__":
    srcs = sources()
    jobs = []
    for sx, sy, sn in srcs:
        jobs += [(f"s{sx}_{sy}_{sn}", (sx, sy, sn)), (f"b_s{sx}_{sy}_{sn}", (sx, sy, sn))]
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        built = dict(zip([j[0] for j in jobs], ex.map(lambda j: build(*j), jobs)))
    res = []
    for sx, sy, sn in srcs:
        dX, dB = built[f"s{sx}_{sy}_{sn}"], built[f"b_s{sx}_{sy}_{sn}"]
        if not dX or not dB:
            print((sx, sy, sn), "FAIL"); continue
        hops = hops_into_L(open(dX + "/top.rcf").read())
        bits = window_bits(open(dB + "/top.rbf", "rb").read(), open(dX + "/top.rbf", "rb").read())
        res.append({"src": [sx, sy, sn], "hops": hops, "bits": sorted([df, db, v] for (df, db), v in bits.items())})
        print((sx, sy, sn), hops, len(bits), flush=True)
    json.dump(res, open(R + f"/fuzz/src_sweep_{X}_{Y}.json", "w"), indent=0)
