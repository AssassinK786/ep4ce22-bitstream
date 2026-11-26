#!/usr/bin/env python3
"""Open place-and-route prototype for the EP4CE22 (DE0-Nano), no Quartus involved.

Flow:  Verilog --yosys (generic synth, abc -lut 4)--> JSON netlist
       --> pack (LUT + DFF into LEs) --> place (annealing over a few LABs)
       --> route (intra-LAB + vertical neighbour links, only hops with decoded codes)
       --> design directory in the format tools/blinky_gen.py reads (extra.qsf placement,
           LUT masks as a .vo, routing hops as pips.json), so the decoded bit models emit the RBF.

Reach of this prototype (what is decoded today):
  * logic in a vertical stack of LABs whose clock tree is measured (default (38,30..32))
  * one global clock from PIN_R8, every FF clocked directly from BLK_CLK_BUF_I5
  * one output: the FF of LE N2 in LAB (38,31) -> LED0 (PIN_A15) (fuzz/paths.json)
  * inputs of a LUT come from: its own FF (datac), an LE local line, an LE buffer of the same LAB
    through a local interconnect line, or a vertical neighbour's buffer (fuzz/li_struct.json);
    a hop is used only if both its line code (li_struct) and its LUT-input code (lim_codes_ll) exist.
usage: python3 tools/pnr/pnr.py design.v NAME [--labs 38,30:38,31:38,32] [--seed N]
"""
import os, re, sys, json, math, random, shutil, subprocess, collections, itertools

R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, R + "/tools")
from rbf import Rbf

LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
LIS = json.load(open(R + "/fuzz/li_struct.json"))
PORTS = ["dataa", "datab", "datac", "datad"]
LED_LAB, LED_LE = (38, 31), 2           # FF N3 of LAB (38,31) drives LED0 (decoded output path)


# ---------------------------------------------------------------- front end
def synth(vfile, out_json):
    subprocess.run(["yosys", "-q", "-p", f"read_verilog {vfile}; synth -flatten -top top; dfflegalize -cell $_DFF_P_ 01; "
                    f"abc -lut 4; opt_clean -purge; write_json {out_json}"], check=True)
    m = json.load(open(out_json))["modules"]["top"]
    ports = {n: (p["direction"], p["bits"]) for n, p in m["ports"].items()}
    luts, dffs = [], []
    for name, c in m["cells"].items():
        if c["type"] == "$lut":
            w = int(c["parameters"]["WIDTH"], 2)
            init = c["parameters"]["LUT"][::-1]               # string is MSB first
            init = [int(ch) for ch in init.ljust(1 << w, "0")]
            luts.append({"name": name, "ins": c["connections"]["A"][:w], "out": c["connections"]["Y"][0], "init": init})
        elif c["type"] == "$_DFF_P_":
            qn = c["connections"]["Q"][0]
            for nn in m["netnames"].values():          # FFs power up at 0; refuse other initial values
                if qn in nn["bits"]:
                    iv = nn.get("attributes", {}).get("init", "")
                    k = nn["bits"].index(qn)
                    if iv and iv[::-1][k:k+1] == "1":
                        sys.exit(f"pnr: {name} has initial value 1; FFs power up at 0 (power-up high is not decoded)")
            dffs.append({"name": name, "d": c["connections"]["D"][0], "q": c["connections"]["Q"][0], "c": c["connections"]["C"][0]})
        else:
            sys.exit(f"pnr: unsupported cell {c['type']} ({name})")
    return ports, luts, dffs


# ---------------------------------------------------------------- pack
def pack(ports, luts, dffs):
    """LEs: {'lut': lut or None, 'ff': dff or None}. A DFF joins the LUT that drives its D."""
    by_out = {l["out"]: l for l in luts}
    used = set()
    les = []
    for f in dffs:
        l = by_out.get(f["d"])
        if l is not None and l["name"] not in used:
            used.add(l["name"])
            les.append({"lut": l, "ff": f})
        else:                                   # route-through LUT: out = in0
            les.append({"lut": {"name": f["name"] + "_rt", "ins": [f["d"]], "out": None, "init": [0, 1]}, "ff": f})
    for l in luts:
        if l["name"] not in used:
            les.append({"lut": l, "ff": None})
    for i, e in enumerate(les):
        e["id"] = i
    return les


def drivers(les):
    """net -> (le id, 'comb' | 'reg')"""
    d = {}
    for e in les:
        if e["lut"]["out"] is not None:
            d[e["lut"]["out"]] = (e["id"], "comb")
        if e["ff"]:
            d[e["ff"]["q"]] = (e["id"], "reg")
    return d


# ---------------------------------------------------------------- place
def place(les, labs, led_net, seed):
    rnd = random.Random(seed)
    drv = drivers(les)
    slots = [(x, y, n) for (x, y) in labs for n in range(0, 32, 2)]
    led_le = drv[led_net][0]
    assert drv[led_net][1] == "reg", "the LED must be driven by a register"
    fixed = {led_le: (LED_LAB[0], LED_LAB[1], LED_LE)}
    free = [s for s in slots if s not in fixed.values()]
    others = [e["id"] for e in les if e["id"] not in fixed]
    if len(others) > len(free):
        sys.exit(f"pnr: {len(les)} LEs do not fit {len(slots)} slots")
    rnd.shuffle(free)
    pos = dict(fixed)
    for i, e in zip(others, free):
        pos[i] = e
    sinks = collections.defaultdict(list)              # net -> LE ids reading it
    for e in les:
        for net in e["lut"]["ins"]:
            sinks[net].append(e["id"])
    lab_of = lambda i: pos[i][:2]

    def cost():
        c = 0
        cross = collections.Counter()
        for net, rd in sinks.items():
            if net not in drv:
                continue
            s = lab_of(drv[net][0])
            for t in {lab_of(i) for i in rd}:
                if t == s:
                    continue
                dy = t[1] - s[1]
                if t[0] != s[0] or abs(dy) != 1:
                    c += 1000                          # no decoded path at all
                else:
                    cross[(s, t)] += 1
                    c += 10
                    # decoded vertical links: down via buffer I30 (LE N30), up via buffer I1 (LE N0)
                    need = 30 if dy == -1 else 0
                    if pos[drv[net][0]][2] != need:
                        c += 500
        c += sum(1000 * (v - 1) for v in cross.values() if v > 1)   # one link per direction
        return c

    cur = cost()
    T = 50.0
    movable = others
    occupied = {v: k for k, v in pos.items()}
    for it in range(int(os.environ.get('PNR_ITERS', '40000'))):
        a = rnd.choice(movable)
        sb = rnd.choice(free + [pos[a]])
        b = occupied.get(sb)
        if b is not None and b in fixed:
            continue
        sa = pos[a]
        pos[a] = sb
        if b is not None:
            pos[b] = sa
        new = cost()
        if new <= cur or rnd.random() < math.exp((cur - new) / T):
            cur = new
            occupied.pop(sa, None); occupied.pop(sb, None)
            occupied[sb] = a
            if b is not None:
                occupied[sa] = b
        else:
            pos[a] = sa
            if b is not None:
                pos[b] = sb
        T = max(0.5, T * (1 - 12.0 / int(os.environ.get('PNR_ITERS', '40000'))))
    return pos, cur


# ---------------------------------------------------------------- route
def route(les, pos):
    """Per LAB: give every LUT input a path with decoded codes. Returns (port maps, hops, problems)."""
    drv = drivers(les)
    hops = []
    portmap = {}
    problems = []
    lab_les = collections.defaultdict(list)
    for e in les:
        lab_les[pos[e["id"]][:2]].append(e)
    # shared resources (by LAB): local line of LE n -> net; buffer b -> net; interconnect line j -> net
    ll, buf, line = {}, {}, {}

    def options(lab, n, port, net):
        """paths (label, resources needed) from net to LE n's port in lab"""
        out = []
        if net not in drv:
            return out
        i, kind = drv[net]
        sx, sy, m = pos[i]
        x, y = lab
        codes = LIM.get(f"N{n}.{port}", {}).get("codes", {})
        if (sx, sy) == lab and m == n and kind == "reg" and port == "datac" and f"FF_N{n+1}" in codes:
            out.append(("own", [], [(f"FF_X{x}_Y{y}_N{n+1}", f"LCCOMB_X{x}_Y{y}_N{n}.datac")]))
        src = (f"FF_X{sx}_Y{sy}_N{m+1}" if kind == "reg" else f"LCCOMB_X{sx}_Y{sy}_N{m}")
        if (sx, sy) == lab and f"LOCAL_LINE_I{m//2}_N0" in codes:
            k = (lab, "ll", m)
            out.append(("ll", [(k, (net, kind))], [(src, f"LOCAL_LINE_X{x}_Y{y}_N0_I{m//2}"),
                                                   (f"LOCAL_LINE_X{x}_Y{y}_N0_I{m//2}", f"LCCOMB_X{x}_Y{y}_N{n}.{port}")]))
        rel = "" if (sx, sy) == lab else f"@{sx-x},{sy-y}"
        for b in (m, m + 1):
            for j in range(38):
                if f"{j}|LE_BUFFER{rel}_I{b}" in LIS and f"LOCAL_INTERCONNECT_I{j}" in codes:
                    res = [((sx, sy, "buf", b), (net, kind)), ((lab, "line", j), net)]
                    out.append(("buf", res, [(src, f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}"),
                                             (f"LE_BUFFER_X{sx}_Y{sy}_N0_I{b}", f"LOCAL_INTERCONNECT_X{x}_Y{y}_N0_I{j}"),
                                             (f"LOCAL_INTERCONNECT_X{x}_Y{y}_N0_I{j}", f"LCCOMB_X{x}_Y{y}_N{n}.{port}")]))
        return out

    owner = {}                                   # resource -> value

    def fits(res):
        return all(owner.get(k, v) == v for k, v in res)

    # the LE local line: also its own output select (comb or reg) -> stored as ("ll", m) owner
    for lab, group in lab_les.items():
        # order LEs by fewest free choices: route hard ones first
        work = []
        for e in group:
            n = pos[e["id"]][2]
            ins = [net for net in e["lut"]["ins"]]
            work.append((e, n, ins))
        def solve(idx, acc):
            if idx == len(work):
                return acc
            e, n, ins = work[idx]
            uniq = list(dict.fromkeys(ins))
            for perm in itertools.permutations(PORTS, len(uniq)):
                plan, added = [], []
                ok = True
                for net, port in zip(uniq, perm):
                    opts = options(lab, n, port, net)
                    opts.sort(key=lambda o: ({"own": 0, "ll": 1, "buf": 2}[o[0]], sum(1 for k, v in o[1] if k not in owner)))
                    chosen = None
                    for o in opts:
                        if fits(o[1]):
                            chosen = o
                            break
                    if chosen is None:
                        ok = False
                        break
                    for k, v in chosen[1]:
                        if k not in owner:
                            owner[k] = v
                            added.append(k)
                    plan.append((net, port, chosen))
                if ok:
                    r = solve(idx + 1, acc + [(e, n, plan)])
                    if r is not None:
                        return r
                for k in added:
                    owner.pop(k, None)
            return None
        work.sort(key=lambda w: -len(set(w[2])))
        res = solve(0, [])
        if res is None:
            alone = []
            for e, n, ins in work:
                if not any(all(options(lab, n, p_, net) for net, p_ in zip(list(dict.fromkeys(ins)), perm))
                           for perm in itertools.permutations(PORTS, len(set(ins)))):
                    alone.append((n, [(net, drv.get(net, ('?',))[1] if net in drv else 'const', pos[drv[net][0]] if net in drv else None) for net in dict.fromkeys(ins)]))
            problems.append(f"LAB {lab}: no complete routing; LEs unroutable even alone: {alone[:3]}")
            continue
        for e, n, plan in res:
            portmap[e["id"]] = {net: port for net, port, _ in plan}
            for net, port, o in plan:
                hops.extend(o[2])
    return portmap, sorted(set(hops)), problems


def mask_for(lut, pm):
    """16-bit lut_mask with the logical inputs on the chosen ports; unused ports don't matter."""
    idx = {p: i for i, p in enumerate(PORTS)}
    m = 0
    for k in range(16):
        li = 0
        for j, net in enumerate(lut["ins"]):
            li |= ((k >> idx[pm[net]]) & 1) << j
        m |= lut["init"][li] << k
    return m


# ---------------------------------------------------------------- write design directory
def write(name, les, pos, pm, hops, clk_net):
    d = f"{R}/work/{name}"
    os.makedirs(d + "/simulation/modelsim", exist_ok=True)
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_A15 -to led"]
    vo, pips = [], list(hops)
    labs_ff = set()
    for e in les:
        x, y, n = pos[e["id"]]
        ln = f"le{e['id']}"
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to {ln}")
        vo.append(f"defparam \\{ln} .lut_mask = 16'h{mask_for(e['lut'], pm[e['id']]):04X};")
        if e["ff"]:
            q.append(f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r{e['id']}")
            pips += [(f"LCCOMB_X{x}_Y{y}_N{n}", f"FF_X{x}_Y{y}_N{n+1}.d"),
                     (f"BLK_CLK_BUF_X{x}_Y{y}_N0_I5", f"FF_X{x}_Y{y}_N{n+1}.clk")]
            labs_ff.add((x, y))
    for (x, y) in labs_ff:
        pips.append((f"LAB_CLK_X{x}_Y{y}_N0_I5", f"BLK_CLK_BUF_X{x}_Y{y}_N0_I5"))
    open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
    open(d + "/simulation/modelsim/top.vo", "w").write("\n".join(vo) + "\n")
    json.dump(sorted(set(map(tuple, pips))), open(d + "/pips.json", "w"))
    # the generator scores against work/<name>/top.rbf: give it the empty-device vote (score only)
    E = [open(f"{R}/work/bl_e{i}/top.rbf", "rb").read() for i in (1, 2, 3)]
    base = Rbf(bytes((a & b) | (a & c) | (b & c) for a, b, c in zip(*E)))
    base.fix_crcs()
    base.save(d + "/top.rbf")
    return d


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    vfile, name = args[0], args[1]
    labs = [(38, 30), (38, 31), (38, 32)]
    if "--labs" in sys.argv:
        labs = [tuple(map(int, s.split(","))) for s in sys.argv[sys.argv.index("--labs") + 1].split(":")]
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1
    os.makedirs(f"{R}/work/pnr", exist_ok=True)
    ports, luts, dffs = synth(vfile, f"{R}/work/pnr/{name}.json")
    les = pack(ports, luts, dffs)
    clk_net = ports["clk"][1][0]
    led_net = ports["led"][1][0]
    print(f"pnr: {len(luts)} LUTs, {len(dffs)} DFFs -> {len(les)} LEs")
    for attempt in range(20):
        pos, c = place(les, labs, led_net, seed + attempt)
        if c >= 1000:
            print(f"pnr: seed {seed + attempt}: placement cost {c} (needs an undecoded inter-LAB path)")
            continue
        pm, hops, probs = route(les, pos)
        if not probs:
            break
        print(f"pnr: seed {seed + attempt}: placement cost {c}, routing failed: {probs}")
    else:
        sys.exit("pnr: no routable placement found")
    print(f"pnr: placed (cost {c}), routed {len(hops)} hops, LABs {sorted({p[:2] for p in pos.values()})}")
    d = write(name, les, pos, pm, hops, clk_net)
    json.dump({"placement": {str(k): v for k, v in pos.items()}, "les": [{"id": e["id"], "lut": e["lut"]["name"], "ff": e["ff"]["name"] if e["ff"] else None} for e in les]},
              open(d + "/pnr.json", "w"), indent=0)
    print(f"pnr: design directory {d}")


if __name__ == "__main__":
    main()
