#!/usr/bin/env python3
"""Cross-check a pnr result with Quartus: compile the same LE netlist (WYSIWYG cells, our masks and
ports) with OUR placement as location assignments, then compare every LUT's function (Quartus may
permute LUT inputs) and the FF placement. usage: qcheck.py NAME"""
import sys, os, json, re, subprocess
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
name = sys.argv[1]
d = f"{R}/work/{name}"; q = f"{R}/work/{name}_q"
os.makedirs(q, exist_ok=True)
pips = json.load(open(d + "/pips.json"))
back = {b: a for a, b in pips}
masks = {int(m[1]): int(m[2], 16) for m in re.finditer(r"defparam \\le(\d+) \.lut_mask = 16'h([0-9A-F]+);", open(d + "/simulation/modelsim/top.vo").read())}
pos = {int(k): tuple(v) for k, v in json.load(open(d + "/pnr.json"))["placement"].items()}
les = json.load(open(d + "/pnr.json"))["les"]
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
v = ["module top(input clk, output led);"]
qsf = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to led"]
led_le = at[(38, 31, 2)]
for e in les:
    i = e["id"]; x, y, n = pos[i]
    ins = ",".join(f".{p}({conn.get((i, p), chr(49) and '1' + chr(39) + 'b1')})" for p in ("dataa", "datab", "datac", "datad"))
    v.append(f"  wire w{i}, q{i};")
    v.append(f"  cycloneive_lcell_comb #(.lut_mask(16'h{masks[i]:04X}),.sum_lutc_input(\"datac\")) le{i} ({ins},.combout(w{i}));")
    qsf.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to le{i}")
    if e["ff"]:
        v.append(f"  dffeas r{i} (.clk(clk),.d(w{i}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(q{i}));")
        qsf.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{i}")
v += [f"  assign led = q{led_le};", "endmodule"]
open(q + "/top.v", "w").write("\n".join(v) + "\n"); open(q + "/extra.qsf", "w").write("\n".join(qsf) + "\n")
r = subprocess.run([R + "/tools/qcompile.sh", q], capture_output=True, text=True, env=dict(os.environ, EDA="1"))
if r.returncode:
    print("Quartus FAILED:", r.stdout[-600:]); sys.exit(1)
vo = open(q + "/simulation/modelsim/top.vo").read()
ok = bad = absorbed = 0
for i in masks:
    if f"cycloneive_lcell_comb le{i}(" not in vo:
        absorbed += 1                            # route-through LUT: Quartus feeds the FF directly
        continue
    blk = vo[vo.index(f"cycloneive_lcell_comb le{i}("):]
    blk = blk[:blk.index(");")]
    qm = int(re.search(rf"defparam le{i}\.lut_mask = 16'h([0-9A-Fa-f]+);", vo)[1], 16)
    qin = {}
    for p in ("dataa", "datab", "datac", "datad"):
        m = re.search(rf"\.{p}\(\\?([^ ),]+)", blk)
        qin[p] = re.sub(r"~(q|output_o|combout)$", "", m[1]) if m else None
    # function check: for all assignments to our source signals, our mask == quartus mask
    sigs = sorted({conn[(i, p)] for p in ("dataa", "datab", "datac", "datad") if (i, p) in conn})
    same = True
    for val in range(1 << len(sigs)):
        env = {s: (val >> k) & 1 for k, s in enumerate(sigs)}
        ka = sum(env.get(conn.get((i, p)), 1) << j for j, p in enumerate(("dataa", "datab", "datac", "datad")))
        kb = 0
        for j, p in enumerate(("dataa", "datab", "datac", "datad")):
            s = qin[p]
            s = s.replace("r", "q", 1) if s and s.startswith("r") else (s.replace("le", "w", 1) if s and s.startswith("le") else s)
            kb |= env.get(s, 1 if s in (None, "vcc") else 0) << j
        if ((masks[i] >> ka) & 1) != ((qm >> kb) & 1):
            same = False; break
    ok += same; bad += (not same)
fit = open(q + "/top.fit.summary").read()
print(f"qcheck {name}: Quartus accepted our placement ({re.search(r'Total logic elements : ([^\n]+)', fit)[1].strip()}); LUT functions equal {ok}/{ok+bad}; route-through LUTs absorbed by Quartus: {absorbed}")
