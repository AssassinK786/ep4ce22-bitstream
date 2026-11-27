#!/usr/bin/env python3
"""Equivalence by simulation: Yosys's netlist (reference) vs our placed-and-routed LE netlist (masks
and connections read back from the design directory), random inputs. Our flow adds one input and
one output register, so ours(t) is compared with reference(t-1) fed with inputs delayed by one cycle.
usage: simcheck2.py NAME VERILOG [cycles] [seed]"""
import sys, os, re, json, random
R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pnr
name, vfile = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
rnd = random.Random(int(sys.argv[4]) if len(sys.argv) > 4 else 1)
d = f"{R}/work/{name}"
info = json.load(open(d + "/pnr.json"))
pnr.load_bundle(info.get("bundle", "all"))
pins = {k: v for k, v in info["pins"].items() if not k.startswith("clk")}

# ---- reference: Yosys netlist
ports, luts, dffs = pnr.synth(vfile, f"{R}/work/pnr/{name}_ref.json")
lut_by_out = {l["out"]: l for l in luts}
chain_bits = {}                                  # chain name -> LEs in order (reference uses plain arithmetic)
for l in luts:
    if l.get("arith"):
        chain_bits.setdefault(l["arith"]["chain"], []).append(l)
for v_ in chain_bits.values():
    v_.sort(key=lambda l: l["arith"]["i"])
def ref_eval(net, st, inp, memo):
    if net in ("0", "1"):
        return int(net)
    if net in memo:
        return memo[net]
    if net in st:
        v = st[net]
    elif net in inp:
        v = inp[net]
    else:
        l = lut_by_out[net]
        if l.get("arith"):
            f0 = chain_bits[l["arith"]["chain"]][0]["arith"]
            carry = (ref_eval(f0["cnet"][0], st, inp, memo) ^ f0["cnet"][1]) if f0.get("cnet") else f0["ci"]
            for x in chain_bits[l["arith"]["chain"]]:
                ar = x["arith"]
                a = ref_eval(ar["a"], st, inp, memo); b = ref_eval(ar["b"], st, inp, memo) ^ ar["bi"]
                if x is l:
                    v = a ^ b ^ carry
                    break
                carry = (a & b) | (carry & (a ^ b))
            memo[net] = v
            return v
        v = l["init"][sum(ref_eval(n_, st, inp, memo) << j for j, n_ in enumerate(l["ins"]))]
    memo[net] = v
    return v
ref_st = {f["q"]: int(f.get("init1", False)) for f in dffs}

# ---- ours: LE netlist from the design directory
masks = {int(m[1]): int(m[2], 16) for m in re.finditer(r"defparam \\le(\d+) \.lut_mask = 16'h([0-9A-F]+);", open(d + "/simulation/modelsim/top.vo").read())}
pos = {int(k): tuple(v) for k, v in info["placement"].items()}
at = {v: k for k, v in pos.items()}
les = {e["id"]: e for e in info["les"]}
pips = json.load(open(d + "/pips.json"))
back = {b: a for a, b in pips}
inport = {}
for b in back:
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$", b)
    if not m:
        continue
    node = back[b]
    while not re.match(r"(FF|LCCOMB)_X\d+_Y\d+_N\d+$", node):
        node = back[node]
    m2 = re.match(r"(FF|LCCOMB)_X(\d+)_Y(\d+)_N(\d+)$", node)
    inport[(at[(int(m[1]), int(m[2]), int(m[3]))], m[4])] = (at[(int(m2[2]), int(m2[3]), int(m2[4]) - (m2[1] == "FF"))], "reg" if m2[1] == "FF" else "comb")
IO = json.load(open(R + "/fuzz/io_paths.json"))
pin_le = {}                                      # input pin -> (le, port)
out_le = {}                                      # output pin -> le
for i, e in les.items():
    m = re.match(r"io_(\w+)_lut$", e["lut"])
    if m:
        pin = m[1]
        if pin in info.get("inputs", []):
            pin_le[pin] = (i, IO[pin]["route"]["port"])
        else:
            out_le[pin] = i
for pin in info.get("absorbed", {}):              # design register placed at the LED's slot: no extra cycle
    sl = tuple(pnr.IO_SLOT[pin])
    out_le[pin] = at[sl]
our_st = {i: 0 for i, e in les.items() if e["ff"]}
prev_in_chain = {}
for ch in info.get("chains", []):
    for a_, b_ in zip(ch, ch[1:]):
        prev_in_chain[b_] = a_
chain_les = {le for ch in info.get("chains", []) for le in ch}
def port_vals(i, inp, memo):
    k = 0
    for j, p in enumerate(pnr.PORTS):
        if (i, p) in inport:
            s_, kind = inport[(i, p)]
            k |= (our_st[s_] if kind == "reg" else our_comb(s_, inp, memo)) << j
    return k
def our_cout(i, inp, memo):
    key = ("co", i)
    if key in memo:
        return memo[key]
    k = port_vals(i, inp, memo)
    cin = our_cout(prev_in_chain[i], inp, memo) if i in prev_in_chain else (((k >> 2) & 1) if (i, "datac") in inport else 1)
    memo[key] = (masks[i] >> ((k & 3) | (cin << 2))) & 1
    return memo[key]
def our_comb(i, inp, memo):
    if i in memo:
        return memo[i]
    if i in chain_les:
        k = port_vals(i, inp, memo)
        cin = our_cout(prev_in_chain[i], inp, memo) if i in prev_in_chain else (((k >> 2) & 1) if (i, "datac") in inport else 1)
        memo[i] = (masks[i] >> (8 | (k & 3) | (cin << 2))) & 1
        return memo[i]
    k = 0
    for j, p in enumerate(pnr.PORTS):
        if (i, p) in inport:
            s, kind = inport[(i, p)]
            k |= (our_st[s] if kind == "reg" else our_comb(s, inp, memo)) << j
    for pin, (le, p) in pin_le.items():
        if le == i:
            k |= inp[pin] << pnr.PORTS.index(p)
    memo[i] = (masks[i] >> k) & 1
    return memo[i]

net_of = {pin: ports[re.match(r"(\w+)\[(\d+)\]", k)[1]][1][int(re.match(r"(\w+)\[(\d+)\]", k)[2])] for k, pin in pins.items()}
in_pins = [p for p in info.get("inputs", [])]
out_pins = [p for p in info.get("outputs", [])]
prev_in = {p: 0 for p in in_pins}
ref_hist, bad = [], 0
for t in range(N):
    cur = {p: prev_in[p] ^ int(rnd.random() < 0.3) for p in in_pins}   # slowly changing inputs
    # reference sees the inputs one cycle late (our input register)
    memo = {}
    rin = {net_of[p]: prev_in[p] for p in in_pins}
    ref_out = {p: ref_eval(net_of[p], ref_st, rin, memo) for p in out_pins}
    ref_hist.append(ref_out)
    ours = {p: our_st[out_le[p]] ^ (p in info.get("inverted_pins", [])) for p in out_pins}
    want = {p: (ref_hist[t][p] if p in info.get("absorbed", {}) else ref_hist[t - 1][p]) for p in out_pins}
    if t >= 2 and ours != want:
        bad += 1
        if bad <= 3:
            print("mismatch at", t, "ours", ours, "expected", want)
    nxt_ref = {f["q"]: ref_eval(f["d"], ref_st, rin, memo) for f in dffs}
    m2 = {}
    nxt_our = {i: our_comb(i, cur, m2) for i in our_st}
    ref_st, our_st, prev_in = nxt_ref, nxt_our, cur
print(f"simcheck2 {name}: {N} cycles, inputs {in_pins}, outputs {out_pins}, {bad} mismatches")
