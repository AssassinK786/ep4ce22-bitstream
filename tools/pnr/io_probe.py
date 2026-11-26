#!/usr/bin/env python3
"""Measure DE0-Nano pin paths for the open flow (clean-room: Quartus RBF / reports / .rcf only).

Each pin gets a fixed slot LE in the measured LAB stack:
  inputs  : the pin enters the slot LE's LUT (route-through) and is registered there;
  outputs : the slot LE's FF drives the pin.
Every probe design also drives LED0 from the FF of LE N2 in LAB (38,31) (decoded path), so the
only thing the bit models don't cover is the pin path itself. The path table is the set of bits
where the models (blinky_gen.py, model-only) differ from Quartus's build: CRAM bits and periphery
bits, with Quartus's values. The .rcf gives the route (local line, LUT port) to reserve.
usage: io_probe.py [PIN ...]      -> fuzz/io_paths.json
"""
import os, re, sys, json, subprocess

R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, R + "/tools")
from rbf import Rbf, F0, FLEN, NFRAMES, PERIPH, PERIPH_LEN
Q = os.environ.get("QUARTUS_BIN", os.path.expanduser("~/altera/13.1/quartus/bin"))
INPUTS = {"J15": (38, 30, 2), "E1": (38, 30, 4), "M1": (38, 30, 6), "T8": (38, 30, 8),
          "B9": (38, 30, 10), "M15": (38, 30, 12)}
# outputs share LAB (38,30) with the inputs, so switch -> LED designs route inside one LAB
OUTPUTS = {"A13": (38, 30, 14), "B13": (38, 30, 16), "A11": (38, 30, 18), "D1": (38, 30, 20),
           "F3": (38, 30, 22), "B1": (38, 30, 24), "L3": (38, 30, 26)}
LED0 = (38, 31, 2)
STA = """project_open top
create_timing_netlist
create_clock -name clk -period 20 [get_ports clk]
update_timing_netlist
report_timing -setup -npaths 20000 -pairs_only -detail full_path -show_routing -file paths.rpt
"""


def design(name, pin, kind):
    x, y, n = INPUTS[pin] if kind == "in" else OUTPUTS[pin]
    lx, ly, ln = LED0
    one = "1'b1"
    ff = lambda r, d, q: (f"  dffeas {r} (.clk(clk),.d({d}),.ena({one}),.clrn({one}),.prn({one}),"
                          f".sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({q}));")
    v = ["module top(input clk, " + ("input p, " if kind == "in" else "output p, ") + "output led);",
         "  wire ws, qs, w0, q0;"]
    if kind == "in":      # slot: LUT pass of the pin, registered
        v.append("  cycloneive_lcell_comb #(.lut_mask(16'h5A5A)) ls (.dataa(p),.datab(1'b1),.datac(qs),.datad(1'b1),.combout(ws));")  # p ^ qs
    else:                 # slot: toggle FF driving the pin
        v.append("  cycloneive_lcell_comb #(.lut_mask(16'h5A5A)) ls (.dataa(q0),.datab(1'b1),.datac(qs),.datad(1'b1),.combout(ws));")  # q0 ^ qs
    v.append(ff("rs", "ws", "qs"))
    v.append("  cycloneive_lcell_comb #(.lut_mask(16'hA5A5)) l0 (.dataa(qs),.datab(1'b1),.datac(q0),.datad(1'b1),.combout(w0));")  # ~(qs ^ q0)
    v.append(ff("r0", "w0", "q0"))
    v += ["  assign led = q0;"] + (["  assign p = qs;"] if kind == "out" else []) + ["endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to led",
         f"set_location_assignment PIN_{pin} -to p",
         f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to ls", f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to rs",
         f"set_location_assignment LCCOMB_X{lx}_Y{ly}_N{ln} -to l0", f"set_location_assignment FF_X{lx}_Y{ly}_N{ln+1} -to r0"]
    d = f"{R}/work/{name}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n")
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


def build(d):
    if not os.path.exists(d + "/top.rbf"):
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True, env=dict(os.environ, EDA="1"))
        if r.returncode:
            raise SystemExit(f"Quartus failed in {d}: {r.stdout[-400:]}")
    if not os.path.exists(d + "/pips.json"):
        sys.path.insert(0, R + "/tools")
        from route_fuzz import parse
        open(d + "/sta.tcl", "w").write(STA)
        subprocess.run([Q + "/quartus_sta", "-t", "sta.tcl"], cwd=d, capture_output=True)
        json.dump(sorted(parse(d + "/paths.rpt")), open(d + "/pips.json", "w"))
    if not os.path.exists(d + "/top.rcf"):
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=d, capture_output=True)


def residual(name):
    """bits where the models differ from Quartus: [('cram', f, byte, bit, qval)], [('pbit', k, bit, qval)]"""
    env = dict(os.environ, DESIGN=name, TREE="clock_tree_pnr.json")
    subprocess.run([sys.executable, R + "/tools/blinky_gen.py"], env=env, capture_output=True, check=True)
    mo = Rbf.load(f"{R}/work/{name}_model_only.rbf").d
    qd = Rbf.load(f"{R}/work/{name}/top.rbf").d
    out = []
    for f in range(NFRAMES):
        o = F0 + FLEN * f
        for b in range(1, 296):
            x = mo[o + b] ^ qd[o + b]
            for k in range(8):
                if x >> k & 1:
                    out.append(["cram", f, b, k, (qd[o + b] >> k) & 1])
    for i in range(PERIPH_LEN // 4):
        p = PERIPH + 4 * i
        x = mo[p] ^ qd[p]
        for k in range(8):
            if x >> k & 1:
                out.append(["pbit", i, k, (qd[p] >> k) & 1])
    return out


def route_of(d, x, y, n):
    """local line and LUT port Quartus used to reach the slot LE (from the .rcf)."""
    rcf = open(d + "/top.rcf").read()
    for blk in re.finditer(r"signal_name = ([^\s{]+) \{(.*?)\n\}", rcf, re.S):
        body = blk[2]
        if blk[1] == "p~input" and "dest = ( ws," in body:
            lines = re.findall(rf"LOCAL_INTERCONNECT:X{x}Y{y}S0I(\d+)", body)
            port = re.search(r"dest = \( ws, DATA[ABCD] \), route_port = (DATA[ABCD])", body)
            return {"signal": blk[1], "lines": sorted({int(l) for l in lines}),
                    "port": port[1].lower() if port else None, "rcf": body.strip()}
    return None


def main():
    pins = sys.argv[1:] or list(INPUTS) + list(OUTPUTS)
    out_f = R + "/fuzz/io_paths.json"
    table = json.load(open(out_f)) if os.path.exists(out_f) else {}
    for kind, slot in (("in", INPUTS["J15"]), ("out", OUTPUTS["A13"])):       # controls: slot, no extra pin
        pass
    for pin in pins:
        kind = "in" if pin in INPUTS else "out"
        name = f"io_{kind}_{pin}"
        d = design(name, pin, kind)
        build(d)
        res = residual(name)
        x, y, n = INPUTS[pin] if kind == "in" else OUTPUTS[pin]
        rt = route_of(d, x, y, n) if kind == "in" else None
        table[pin] = {"kind": kind, "slot": [x, y, n], "bits": res, "route": rt}
        print(f"{pin:4s} {kind:3s} slot {x},{y} N{n}: {sum(1 for e in res if e[0]=='cram')} CRAM + "
              f"{sum(1 for e in res if e[0]=='pbit')} periphery bits"
              + (f"; route line(s) {rt['lines']} port {rt['port']}" if rt else ""), flush=True)
        json.dump(table, open(out_f, "w"), indent=0)




def design_all(name="io_all"):
    """All 6 inputs and 8 LEDs at their slots in one design, so Quartus picks non-colliding pin routes.
    Inputs: slot LE = pin ^ own FF; XOR tree in LAB (38,30) ending at LE N0 (vertical link up to LAB 31);
    LED0 FF (38,31) N3 = q0 ^ tree. Outputs: ring of toggles in LAB (38,32), slot k: qk ^ q(k+1)."""
    one = "1'b1"
    ff = lambda r, d_, q_: (f"  dffeas {r} (.clk(clk),.d({d_}),.ena({one}),.clrn({one}),.prn({one}),"
                            f".sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({q_}));")
    lut = lambda n_, m, a, b, c, dd, o: f"  cycloneive_lcell_comb #(.lut_mask(16'h{m:04X})) {n_} (.dataa({a}),.datab({b}),.datac({c}),.datad({dd}),.combout({o}));"
    xor_mask = lambda k: sum((bin(i & ((1 << k) - 1)).count("1") & 1) << i for i in range(16))
    ins, outs = list(INPUTS), list(OUTPUTS)
    v = ["module top(input clk, " + ", ".join(f"input i_{p}" for p in ins) + ", " +
         ", ".join(f"output o_{p}" for p in outs) + ", output led);"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to led"]
    for p in ins:
        x, y, n = INPUTS[p]
        v += [f"  wire w_{p}, q_{p};", lut(f"ls_{p}", 0x5A5A, f"i_{p}", one, f"q_{p}", one, f"w_{p}"), ff(f"rs_{p}", f"w_{p}", f"q_{p}")]
        q += [f"set_location_assignment PIN_{p} -to i_{p}", f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to ls_{p}",
              f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to rs_{p}"]
    v += ["  wire x1, x2, w0, q0;",
          lut("lx1", xor_mask(4), *(f"q_{p}" for p in ins[:4]), "x1"),
          lut("lx2", xor_mask(3), "x1", f"q_{ins[4]}", f"q_{ins[5]}", one, "x2"),
          lut("l0", 0x5A5A, "x2", one, "q0", one, "w0"), ff("r0", "w0", "q0"), "  assign led = q0;"]
    q += ["set_location_assignment LCCOMB_X38_Y30_N28 -to lx1", "set_location_assignment LCCOMB_X38_Y30_N0 -to lx2",
          "set_location_assignment LCCOMB_X38_Y31_N2 -to l0", "set_location_assignment FF_X38_Y31_N3 -to r0"]
    for k, p in enumerate(outs):
        x, y, n = OUTPUTS[p]
        nxt = outs[(k + 1) % len(outs)]
        v += [f"  wire w_{p}, q_{p};", lut(f"ls_{p}", 0x5A5A, f"q_{nxt}", one, f"q_{p}", one, f"w_{p}"),
              ff(f"rs_{p}", f"w_{p}", f"q_{p}"), f"  assign o_{p} = q_{p};"]
        q += [f"set_location_assignment PIN_{p} -to o_{p}", f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to ls_{p}",
              f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to rs_{p}"]
    v.append("endmodule")
    d = f"{R}/work/{name}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("\n".join(v) + "\n")
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    return d


def main_all():
    d = design_all()
    build(d)
    res = residual("io_all")
    rcf = open(d + "/top.rcf").read()
    routes = {}
    for p in INPUTS:
        x, y, n = INPUTS[p]
        m = re.search(rf"signal_name = i_{p}~input \{{(.*?)\n\}}", rcf, re.S)
        body = m[1] if m else ""
        routes[p] = {"lines": sorted({int(l) for l in re.findall(rf"LOCAL_INTERCONNECT:X{x}Y{y}S0I(\d+)", body)}),
                     "port": (re.search(rf"dest = \( w_{p}, DATA[ABCD] \), route_port = (DATA[ABCD])", body) or [None, None])[1]}
        routes[p]["port"] = routes[p]["port"].lower() if routes[p]["port"] else None
    out_f = R + "/fuzz/io_paths_all.json"
    json.dump({"inputs": INPUTS, "outputs": OUTPUTS, "bits": res, "routes": routes}, open(out_f, "w"), indent=0)
    print(f"io_all: {sum(1 for e in res if e[0]=='cram')} CRAM + {sum(1 for e in res if e[0]=='pbit')} periphery bits; routes {routes}")


if __name__ == "__main__":
    main_all() if sys.argv[1:2] == ["--all"] else main()
