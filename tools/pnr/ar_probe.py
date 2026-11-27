#!/usr/bin/env python3
"""Carry-chain probes (clean-room: Quartus RBF / reports only).

Arithmetic-mode LE semantics, read from Quartus's own counter masks (work/ar_rtl):
  cin takes datac's place; combout = mask[8 + a + 2b + 4cin] (datad = 1); cout = mask[a + 2b + 4cin].
  The carry alternates polarity with the LE's position k = N/2: cout is inverted when k is even;
  cin is inverted when k is odd (the LE below it inverted). A chain runs N0 -> N30, then on to N0 of
  the LAB below (y - 1).
A probe is a counter: c0 in a normal LE, c1..cK in a chain at fixed LEs, c(K) -> LED0 through the LED0
LE in (38,31). The bits where the models differ from Quartus's build are the arithmetic/carry bits.
usage: ar_probe.py START_X START_Y START_N LENGTH NAME"""
import os, sys, json, subprocess
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, R + "/tools/pnr")
import io_probe


def chain_positions(x, y, n, length):
    out = []
    for _ in range(length):
        out.append((x, y, n))
        n += 2
        if n > 30:
            n, y = 0, y - 1
    return out


def arith_mask(sum_f, cout_f):
    """sum_f, cout_f: functions of (a, b, cin) -> bit; returns the 16-bit lut_mask"""
    m = 0
    for a in (0, 1):
        for b in (0, 1):
            for c in (0, 1):
                i = a + 2 * b + 4 * c
                m |= cout_f(a, b, c) << i
                m |= sum_f(a, b, c) << (8 + i)
    return m


def counter_bit_mask(k, first, last):
    """LE at position k holding counter bit on datab: sum = b ^ carry_in, carry_out = b & carry_in.
    Physical polarity: cin inverted if k odd (and not the chain's first LE), cout inverted if k even."""
    cin_inv = (k % 2 == 1) and not first
    cout_inv = (k % 2 == 0)
    def carry_in(c):
        return 1 if first else (c ^ cin_inv)
    s = lambda a, b, c: b ^ carry_in(c)
    co = lambda a, b, c: (b & carry_in(c)) ^ cout_inv if not last else 0
    return arith_mask(s, co)


def design(name, pos):
    one = "1'b1"
    ff = lambda r, d_, q_: (f"  dffeas {r} (.clk(clk),.d({d_}),.ena({one}),.clrn({one}),.prn({one}),"
                            f".sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({q_}));")
    K = len(pos)
    v = ["module top(input clk, output led);", f"  wire [{K}:0] q, w;", f"  wire [{K}:0] co;"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to led"]
    # c0: plain LE toggling (carry in for c1 is c0 itself: chain starts with cin = 1 via first-LE rule on c0's value)
    x0, y0, n0 = pos[0][0], pos[0][1], (pos[0][2] - 2) % 32 if pos[0][2] >= 2 else 30
    y0 = pos[0][1] if pos[0][2] >= 2 else pos[0][1] + 1
    v += [f"  cycloneive_lcell_comb #(.lut_mask(16'h0F0F)) l0 (.dataa({one}),.datab({one}),.datac(q[0]),.datad({one}),.combout(w[0]));",
          ff("r0", "w[0]", "q[0]")]
    q += [f"set_location_assignment LCCOMB_X{x0}_Y{y0}_N{n0} -to l0", f"set_location_assignment FF_X{x0}_Y{y0}_N{n0+1} -to r0"]
    for i, (x, y, n) in enumerate(pos, start=1):
        k = n // 2
        first, last = i == 1, i == K
        if first:               # chain start: sum = b ^ a, cout = a & b (a = c0, b = c1), no cin
            cout_inv = (k % 2 == 0)
            m = arith_mask(lambda a, b, c: a ^ b, lambda a, b, c: (a & b) ^ cout_inv)
            ins = f".dataa(q[0]),.datab(q[1]),.datad({one}),.cin(1'b0)"
        else:
            m = counter_bit_mask(k, False, last)
            ins = f".dataa(1'b0),.datab(q[{i}]),.datad({one}),.cin(co[{i-1}])"
        v.append(f"  cycloneive_lcell_comb #(.lut_mask(16'h{m:04X}),.sum_lutc_input(\"cin\")) l{i} ({ins},.combout(w[{i}])"
                 + ("" if last else f",.cout(co[{i}])") + ");")
        v.append(ff(f"r{i}", f"w[{i}]", f"q[{i}]"))
        q += [f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l{i}", f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{i}"]
    v += ["  wire wl, ql;",
          f"  cycloneive_lcell_comb #(.lut_mask(16'h5A5A)) ll (.dataa(q[{K}]),.datab({one}),.datac(ql),.datad({one}),.combout(wl));",
          ff("rl", "wl", "ql"), "  assign led = ql;", "endmodule"]
    q += ["set_location_assignment LCCOMB_X38_Y31_N2 -to ll", "set_location_assignment FF_X38_Y31_N3 -to rl"]
    d = f"{R}/work/{name}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n")
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


if __name__ == "__main__":
    x, y, n, L, name = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    pos = chain_positions(x, y, n, L)
    d = design(name, pos)
    io_probe.build(d)
    vo = open(d + "/simulation/modelsim/top.vo").read()
    res = io_probe.residual(name)
    json.dump({"pos": pos, "bits": res}, open(d + "/arith_residual.json", "w"))
    print(f"{name}: chain {pos[0]}..{pos[-1]} ({L} LEs): {len(res)} residual bits:", [e for e in res][:30])
