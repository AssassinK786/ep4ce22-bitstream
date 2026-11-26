#!/usr/bin/env python3
"""DE0-Nano blinky for the bit-level generator: a 26-bit synchronous counter without
carry chains (LUT4 + FF per bit, plus a toggle-enable LUT every 3 bits), pinned in the
LABs X38 Y31..33 next to the A15 pad. q[25] drives LED0 (A15), clock 50 MHz on R8.
Writes work/<name>/top.v + extra.qsf.
"""
import os, sys
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NB = 26
name = sys.argv[1] if len(sys.argv) > 1 else "bl_full"
d = f"{R}/work/{name}"
os.makedirs(d, exist_ok=True)
slots = [(38, y, n) for y in (33, 32, 31) for n in range(0, 32, 2)]
v = ["module top(input clk, output led);", f"  wire [{NB-1}:0] q;", "  wire [31:0] t;", "  assign t[0] = 1'b1;"]
q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to led"]
k = 0
def le(lut, mask, a, b, c, dd, ff=None):
    global k
    x, y, n = slots[k]; k += 1
    v.append(f"  wire {lut}_o; cycloneive_lcell_comb #(.lut_mask(16'h{mask:04x})) {lut} (.dataa({a}),.datab({b}),.datac({c}),.datad({dd}),.combout({lut}_o));")
    q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to {lut}")
    if ff:
        v.append(f"  dffeas {ff[0]} (.clk(clk),.d({lut}_o),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({ff[1]}));")
        q.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to {ff[0]}")
# group g covers bits 3g..3g+2 with enable t[g] (t[0]=1): d_i = q_i ^ (t & prefix AND)
for g in range((NB + 2) // 3):
    i0 = 3 * g
    tg = f"t[{g}]"
    for j in range(3):
        i = i0 + j
        if i >= NB:
            break
        # inputs: a=q_i, b=t, c=q_i0, d=q_i0+1 ; enable = t & (j>=1? q_i0) & (j>=2? q_i0+1)
        a, b = f"q[{i}]", tg
        c = f"q[{i0}]" if j >= 1 else "1'b1"
        dd = f"q[{i0+1}]" if j >= 2 else "1'b1"
        mask = 0
        for idx in range(16):
            A, B, C, D = idx & 1, idx >> 1 & 1, idx >> 2 & 1, idx >> 3 & 1
            en = B & (C if j >= 1 else 1) & (D if j >= 2 else 1)
            mask |= (A ^ en) << idx
        le(f"l{i}", mask, a, b, c, dd, ff=(f"r{i}", f"q[{i}]"))
    if i0 + 3 < NB:
        # t[g+1] = t[g] & q_i0 & q_i0+1 & q_i0+2
        mask = 1 << 15
        le(f"lt{g+1}", mask, tg, f"q[{i0}]", f"q[{i0+1}]", f"q[{i0+2}]")
        v.append(f"  assign t[{g+1}] = lt{g+1}_o;")
v += [f"  assign led = q[{NB-1}];", "endmodule"]
open(d + "/top.v", "w").write("\n".join(v) + "\n")
open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
print(name, "LEs", k)
