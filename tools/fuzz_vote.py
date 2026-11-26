#!/usr/bin/env python3
"""Three-design votes (X vs Y1, Y2): bits where X differs from both and Y1 == Y2 belong to X's
feature only.
  path:  X = M1 -> FF(38,31,N3) -> A15 ; Y1 = ... -> A13 ; Y2 = ... -> B13   (clock R8 in all)
  clock: X = FFs at (38,31..33) clocked by R8 ; Y1 = clocked by E1 ; Y2 = clocked by J15
Builds in work/vt_<tag>; solve: python3 tools/fuzz_vote.py solve -> fuzz/paths.json, fuzz/clock_tree.json
"""
import os, sys, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
FF = "dffeas {n} (.clk({c}),.d({d}),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q({q}));"


def design(tag):
    if tag.startswith("path_"):
        pin = tag.split("_")[1]
        v = "module top(input clk, input a, output y);\n  " + FF.format(n="r", c="clk", d="a", q="y") + "\nendmodule\n"
        q = f"set_location_assignment PIN_R8 -to clk\nset_location_assignment PIN_M1 -to a\nset_location_assignment PIN_{pin} -to y\nset_location_assignment FF_X38_Y31_N3 -to r\n"
    else:
        cpin = tag.split("_")[1]
        v = ("module top(input clk, input a, output y);\n  wire q1, q2, q3;\n  "
             + FF.format(n="r1", c="clk", d="a", q="q1") + "\n  " + FF.format(n="r2", c="clk", d="q1", q="q2") + "\n  "
             + FF.format(n="r3", c="clk", d="q2", q="q3") + "\n  assign y = q3;\nendmodule\n")
        q = (f"set_location_assignment PIN_{cpin} -to clk\nset_location_assignment PIN_M1 -to a\nset_location_assignment PIN_A15 -to y\n"
             "set_location_assignment FF_X38_Y31_N1 -to r1\nset_location_assignment FF_X38_Y32_N1 -to r2\nset_location_assignment FF_X38_Y33_N1 -to r3\n")
    d = f"{R}/work/vt_{tag}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write(v); open(d + "/extra.qsf", "w").write(q)
    return d


TAGS = ["path_A15", "path_A13", "path_B13", "clk_R8", "clk_E1", "clk_J15"]


def run(tag):
    d = design(tag)
    if not os.path.exists(d + "/top.rbf"):
        r = subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True, text=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
        if r.returncode:
            return tag, "FAIL " + (r.stdout + r.stderr)[-250:].replace("\n", " ")
    return tag, "ok"


def vote(x, y1, y2):
    from rbf import F0, FLEN, NFRAMES, PERIPH, PERIPH_LEN
    X, A, B = (open(f"{R}/work/vt_{t}/top.rbf", "rb").read() for t in (x, y1, y2))
    out = []
    for f in range(NFRAMES):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            i = o + byte
            m = (X[i] ^ A[i]) & (X[i] ^ B[i]) & ~(A[i] ^ B[i]) & 0xFF
            for bit in range(8):
                if m >> bit & 1:
                    out.append(["cram", f, byte, bit, (X[i] >> bit) & 1])
    for k in range(PERIPH_LEN // 4):
        i = PERIPH + 4 * k
        if X[i] != A[i] and X[i] != B[i] and A[i] == B[i]:
            out.append(["periph", k, X[i]])
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["solve"]:
        p = vote("path_A15", "path_A13", "path_B13")
        c = vote("clk_R8", "clk_E1", "clk_J15")
        json.dump({"A15_from_38_31_N3": p}, open(R + "/fuzz/paths.json", "w"), indent=0)
        json.dump({"R8_to_38_31_32_33": c}, open(R + "/fuzz/clock_tree.json", "w"), indent=0)
        print("path bits", sum(e[0] == "cram" for e in p), "periph", sum(e[0] == "periph" for e in p))
        print("clock tree bits", sum(e[0] == "cram" for e in c), "periph", sum(e[0] == "periph" for e in c))
    else:
        with cf.ThreadPoolExecutor(2) as ex:
            for tag, res in ex.map(run, TAGS):
                print(tag, res, flush=True)
