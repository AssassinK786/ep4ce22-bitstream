#!/usr/bin/env python3
"""Cycle-simulate a pnr result at LE level (masks as emitted, inputs on the routed ports) and
compare the counter register 'c' with a reference model. usage: simcheck.py NAME VERILOG [cycles]"""
import sys, os, json, re
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pnr
name, vfile = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
d = f"{R}/work/{name}"
js = json.load(open(f"{R}/work/pnr/{name}.json"))["modules"]["top"]
ports, luts, dffs = pnr.synth(vfile, f"{R}/work/pnr/{name}_chk.json")
les = pnr.pack(ports, luts, dffs)
# masks and ports exactly as written: parse the .vo and the routed hops
masks = {int(m[1]): int(m[2], 16) for m in re.finditer(r"defparam \\le(\d+) \.lut_mask = 16'h([0-9A-F]+);", open(d + "/simulation/modelsim/top.vo").read())}
pl = json.load(open(d + "/pnr.json"))["placement"]
pos = {int(k): tuple(v) for k, v in pl.items()}
at = {v: k for k, v in pos.items()}
drv = pnr.drivers(les)
inport = {}                                     # (le, port) -> net, from the routed hops
for a, b in json.load(open(d + "/pips.json")):
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$", b)
    if not m:
        continue
    le = at[(int(m[1]), int(m[2]), int(m[3]))]
    src = None
    m2 = re.match(r"(FF|LCCOMB)_X(\d+)_Y(\d+)_N(\d+)$", a)
    # walk back to the driving LE through the hop list
    back = {bb: aa for aa, bb in json.load(open(d + "/pips.json"))}
    node = a
    while not re.match(r"(FF|LCCOMB)_X\d+_Y\d+_N\d+$", node):
        node = back[node]
    m2 = re.match(r"(FF|LCCOMB)_X(\d+)_Y(\d+)_N(\d+)$", node)
    n2 = int(m2[4]) - (1 if m2[1] == "FF" else 0)
    src_le = at[(int(m2[2]), int(m2[3]), n2)]
    inport[(le, m[4])] = (src_le, "reg" if m2[1] == "FF" else "comb")
state = {e["id"]: 0 for e in les if e["ff"]}
INIT1 = None
REG = "c" if "c" in js["netnames"] else "s"
cbits = js["netnames"][REG]["bits"]
ref = 0
q_of = {e["ff"]["q"]: e["id"] for e in les if e["ff"]}
def comb(le, memo):
    if le in memo:
        return memo[le]
    k = 0
    for i, p in enumerate(pnr.PORTS):
        if (le, p) in inport:
            s, kind = inport[(le, p)]
            v = state[s] if kind == "reg" else comb(s, memo)
            k |= v << i
    memo[le] = (masks[le] >> k) & 1
    return memo[le]
bad = 0
for cyc in range(N):
    val = sum(state[q_of[b]] << i for i, b in enumerate(cbits))
    if REG == "c":
        ref = cyc % (1 << len(cbits))
    elif cyc:
        ref = ((ref << 1) & 0xFFFFFF) | (~((ref >> 23) ^ (ref >> 22) ^ (ref >> 21) ^ (ref >> 16)) & 1)
    if val != ref:
        bad += 1
        if bad < 4: print("mismatch at", cyc, val)
    memo = {}
    nxt = {le: comb(le, memo) for le in state}
    state = nxt
print(f"simcheck {name}: {N} cycles, {bad} mismatches; inputs routed {len(inport)}")
