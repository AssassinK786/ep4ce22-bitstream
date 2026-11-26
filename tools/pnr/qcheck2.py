#!/usr/bin/env python3
"""Quartus cross-check for pnr designs with I/O pins.
1. Compile our LE netlist (our masks, our port use, our placement as location assignments, our pins)
   and compare every LUT's function with Quartus's.
2. Run the bit models + pin bundle on Quartus's routing of the same placement and compare with
   Quartus's bitstream (CRAM bits and periphery bits), split by area.
usage: qcheck2.py NAME"""
import sys, os, re, json, subprocess, collections
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, R + "/tools"); sys.path.insert(0, R + "/tools/pnr")
from rbf import Rbf, F0, FLEN, NFRAMES, PERIPH, PERIPH_LEN
import pnr
name = sys.argv[1]
d = f"{R}/work/{name}"; q = f"{R}/work/{name}_q"
os.makedirs(q, exist_ok=True)
info = json.load(open(d + "/pnr.json"))
pips = json.load(open(d + "/pips.json"))
back = {b: a for a, b in pips}
masks = {int(m[1]): int(m[2], 16) for m in re.finditer(r"defparam \\le(\d+) \.lut_mask = 16'h([0-9A-F]+);", open(d + "/simulation/modelsim/top.vo").read())}
pos = {int(k): tuple(v) for k, v in info["placement"].items()}
les = {e["id"]: e for e in info["les"]}
at = {v: k for k, v in pos.items()}
def src_of(node):
    while not re.match(r"(FF|LCCOMB)_X\d+_Y\d+_N\d+$", node):
        node = back[node]
    m = re.match(r"(FF|LCCOMB)_X(\d+)_Y(\d+)_N(\d+)$", node)
    le = at[(int(m[2]), int(m[3]), int(m[4]) - (1 if m[1] == "FF" else 0))]
    return f"q{le}" if m[1] == "FF" else f"w{le}"
conn = {}
for a, b in pips:
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$", b)
    if m:
        conn[(at[(int(m[1]), int(m[2]), int(m[3]))], m[4])] = src_of(a)
ins, outs = info.get("inputs", []), info.get("outputs", [])
for i, e in les.items():                         # input LEs: the pin on its measured port
    m = re.match(r"io_(\w+)_lut$", e["lut"])
    if m and m[1] in ins:
        conn[(i, pnr.IO[m[1]]["route"]["port"])] = f"pin_{m[1]}"
out_le = {}
for pin in outs:
    out_le[pin] = at[tuple(pnr.IO_SLOT[pin])]
v = ["module top(input clk" + "".join(f", input pin_{p}" for p in ins) + "".join(f", output o_{p}" for p in outs) + ");"]
qsf = ["set_location_assignment PIN_R8 -to clk"] + [f"set_location_assignment PIN_{p} -to pin_{p}" for p in ins] + \
      [f"set_location_assignment PIN_{p} -to o_{p}" for p in outs]
for i, e in les.items():
    x, y, n = pos[i]
    cs = ",".join(f".{p}({conn.get((i, p), '1' + chr(39) + 'b1')})" for p in pnr.PORTS)
    v.append(f"  wire w{i}, q{i};")
    v.append(f"  cycloneive_lcell_comb #(.lut_mask(16'h{masks[i]:04X}),.sum_lutc_input(\"datac\")) le{i} ({cs},.combout(w{i}));")
    qsf.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to le{i}")
    if e["ff"]:
        v.append(f"  dffeas r{i} (.clk(clk),.d(w{i}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(q{i}));")
        qsf.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{i}")
v += [f"  assign o_{p} = q{out_le[p]};" for p in outs] + ["endmodule"]
open(q + "/top.v", "w").write("\n".join(v) + "\n"); open(q + "/extra.qsf", "w").write("\n".join(qsf) + "\n")
if not os.path.exists(q + "/top.rbf"):
    r = subprocess.run([R + "/tools/qcompile.sh", q], capture_output=True, text=True, env=dict(os.environ, EDA="1"))
    if r.returncode:
        sys.exit("Quartus FAILED: " + r.stdout[-600:])
vo = open(q + "/simulation/modelsim/top.vo").read()
ok = bad = absorbed = 0
for i in masks:
    if f"cycloneive_lcell_comb le{i}(" not in vo:
        absorbed += 1
        continue
    blk = vo[vo.index(f"cycloneive_lcell_comb le{i}("):]; blk = blk[:blk.index(");")]
    qm = int(re.search(rf"defparam le{i}\.lut_mask = 16'h([0-9A-Fa-f]+);", vo)[1], 16)
    qin = {}
    for p in pnr.PORTS:
        m = re.search(rf"\.{p}\(\\?([^ ),]+)", blk)
        s = re.sub(r"~(q|output_o|combout|input_o)$", "", m[1]) if m else None
        if s and s.startswith("r") and s[1:].isdigit(): s = "q" + s[1:]
        if s and s.startswith("le") and s[2:].isdigit(): s = "w" + s[2:]
        qin[p] = s
    sigs = sorted({conn[(i, p)] for p in pnr.PORTS if (i, p) in conn})
    same = True
    for val in range(1 << len(sigs)):
        env = {s: (val >> k) & 1 for k, s in enumerate(sigs)}
        ka = sum(env.get(conn.get((i, p)), 1) << j for j, p in enumerate(pnr.PORTS))
        kb = sum(env.get(qin[p], 1 if qin[p] in (None, "vcc") else 0) << j for j, p in enumerate(pnr.PORTS))
        if ((masks[i] >> ka) & 1) != ((qm >> kb) & 1):
            same = False; break
    ok += same; bad += (not same)
fit = open(q + "/top.fit.summary").read()
print(f"qcheck2 {name}: Quartus accepted our placement and pins ({re.search(r'Total logic elements : ([^\n]+)', fit)[1].strip()}); "
      f"LUT functions equal {ok}/{ok+bad}; LUTs Quartus absorbed: {absorbed}")
# 2. models + bundle on Quartus's routing of the same placement
from route_fuzz import STA, parse
if not os.path.exists(q + "/pips.json"):
    open(q + "/sta.tcl", "w").write(STA.replace("-from_clock clk -to_clock clk ", ""))
    subprocess.run([pnr_q := os.path.expanduser("~/altera/13.1/quartus/bin") + "/quartus_sta", "-t", "sta.tcl"], cwd=q, capture_output=True)
    json.dump(sorted(parse(q + "/paths.rpt")), open(q + "/pips.json", "w"))
json.dump({**info, "placement": info["placement"]}, open(q + "/pnr.json", "w"))
# Quartus turns our route-through LUTs into "r<i>~feeder" cells in the same LE: give the models their masks
vo_t = open(q + "/simulation/modelsim/top.vo").read()
extra = []
nolut = []
for i in masks:
    if f"defparam le{i}.lut_mask" not in vo_t and f"defparam \\le{i} .lut_mask" not in vo_t:
        m = re.search(rf"defparam \\r{i}~feeder \.lut_mask = 16'h([0-9A-Fa-f]+);", vo_t)
        if m:
            extra.append(f"defparam le{i}.lut_mask = 16'h{m[1]};")
        else:          # Quartus feeds the FF directly (no LUT): the models must not expect one there
            print(f"   note: LE {i} has neither a LUT nor a feeder in Quartus's netlist (FF fed directly)")
            lines_ = [l_ for l_ in open(q + "/extra.qsf").read().splitlines() if not l_.endswith(f" -to le{i}")]
            open(q + "/extra.qsf", "w").write("\n".join(lines_) + "\n")
            nolut.append(i)
if extra:
    open(q + "/simulation/modelsim/top.vo", "a").write("\n" + "\n".join(extra) + "\n")
    print(f"   {len(extra)} feeder masks mapped to our LE names")
r = subprocess.run([sys.executable, R + "/tools/pnr/emit.py", f"{name}_q"], capture_output=True, text=True)
print("  ", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
mo = Rbf.load(f"{R}/work/{name}_q_open.rbf").d; qd = Rbf.load(q + "/top.rbf").d
area = collections.Counter(); diffs = []
for f in range(NFRAMES):
    o = F0 + FLEN * f
    for b in range(1, 296):
        x = mo[o + b] ^ qd[o + b]
        for k in range(8):
            if x >> k & 1:
                diffs.append((f, b, k)); area["col 38 frames" if 1820 <= f <= 1900 else "elsewhere"] += 1
pdiff = sum(bin(mo[PERIPH + 4 * i] ^ qd[PERIPH + 4 * i]).count("1") for i in range(PERIPH_LEN // 4))
print(f"   models + pin bundle on Quartus's routing vs Quartus: {len(diffs)} CRAM bits {dict(area)}, {pdiff} periphery bits; "
      f"byte-identical: {bytes(mo) == bytes(qd)}")
json.dump(diffs, open(q + "/qcheck2_diff.json", "w"))
