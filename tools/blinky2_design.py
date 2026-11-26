#!/usr/bin/env python3
"""DE0-Nano blinky v2: 24-bit counter in TWO LABs, minimal inter-LAB routing.
LAB A (38,32): bits 0..11 + enables t1..t4 (t4 is the only net leaving the LAB).
LAB B (38,31): bits 12..23 + enables t5..t7; bit 23's FF at N3 drives LED0 (A15).
Counter LE: d_i = q_i ^ (t_g & q_g0 & q_g1) for its 3-bit group g (LUT4, FF);
enable LE: t_{g+1} = t_g & q_g0 & q_g1 & q_g2 (LUT4, comb). 50 MHz / 2^24 -> LED toggles every ~0.17 s.
Writes work/<name>/top.v + extra.qsf."""
import os, sys
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
name = sys.argv[1] if len(sys.argv) > 1 else "bl2_full"
# optional: xA yA xB yB [pin]  (LAB A holds bits 0..11, LAB B bits 12..23; LED FF at B N3)
XA, YA, XB, YB = (map(int, sys.argv[2:6]) if len(sys.argv) > 5 else (38, 32, 38, 31))
PIN = sys.argv[6] if len(sys.argv) > 6 else "A15"
d = f"{R}/work/{name}"; os.makedirs(d, exist_ok=True)
NB = 24
v = ["module top(input clk, output led);", f"  wire [{NB-1}:0] q;", "  wire [8:0] t;", "  assign t[0] = 1'b1;"]
q = ["set_location_assignment PIN_R8 -to clk", f"set_location_assignment PIN_{PIN} -to led"]
slots = {"A": [(XA, YA, n) for n in range(0, 32, 2)], "B": [(XB, YB, n) for n in range(0, 32, 2) if n != 2]}
used = {"A": 0, "B": 0}
def take(lab, fixed=None):
    if fixed:
        return fixed
    s = slots[lab][used[lab]]; used[lab] += 1; return s
def le(lut, mask, ins, lab, ff=None, fixed=None):
    x, y, n = take(lab, fixed)
    v.append(f"  wire {lut}_o; cycloneive_lcell_comb #(.lut_mask(16'h{mask:04x})) {lut} (.dataa({ins[0]}),.datab({ins[1]}),.datac({ins[2]}),.datad({ins[3]}),.combout({lut}_o));")
    q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to {lut}")
    if ff:
        v.append(f"  dffeas {ff[0]} (.clk(clk),.d({lut}_o),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({ff[1]}));")
        q.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to {ff[0]}")
for g in range(NB // 3):
    lab = "A" if g < 4 else "B"
    i0, tg = 3 * g, f"t[{g}]"
    for j in range(3):
        i = i0 + j
        c = f"q[{i0}]" if j >= 1 else "1'b1"
        dd = f"q[{i0+1}]" if j >= 2 else "1'b1"
        mask = 0
        for idx in range(16):
            A, B, C, D = idx & 1, idx >> 1 & 1, idx >> 2 & 1, idx >> 3 & 1
            mask |= (A ^ (B & (C if j >= 1 else 1) & (D if j >= 2 else 1))) << idx
        le(f"l{i}", mask, [f"q[{i}]", tg, c, dd], lab, ff=(f"r{i}", f"q[{i}]"), fixed=(XB, YB, 2) if i == NB - 1 else None)
    if i0 + 3 < NB:
        le(f"lt{g+1}", 1 << 15, [tg, f"q[{i0}]", f"q[{i0+1}]", f"q[{i0+2}]"], lab)
        v.append(f"  assign t[{g+1}] = lt{g+1}_o;")
v += [f"  assign led = q[{NB-1}];", "endmodule"]
open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
print(name, used)
