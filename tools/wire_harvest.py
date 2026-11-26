#!/usr/bin/env python3
"""Inter-LAB wire codes from naturally routed single-net designs (clean-room: Quartus in/out only).

Design k: source FF at a random LE of LAB S (fed from pin M1 through its own LUT) drives ONLY the datab input
of LUT N0 in LAB D (another LAB of the region); D.N0 -> pin A15.
Base k: the same design with no source LE and D.N0.datab = 0.
The .rcf of design k gives the exact route (LE_BUFFER -> wires -> LOCAL_INTERCONNECT -> dest).
on_k = CRAM bits that are 1 in design k and 0 in base k, minus every element-plane position of S and D
(LUT contents, LUT-input muxes, frames -1/8/9/11 of those LABs) = union of the codes of the route's hops.
Output: work/wh_<k>/ {top.rbf, top.rcf, base/top.rbf} and fuzz/wire_harvest.json [{k, S, D, route, on}]
usage: J=2 N=200 python3 tools/wire_harvest.py [solve]
"""
import os, sys, re, json, random, subprocess, collections, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES
sys.argv_save = list(sys.argv); sys.argv = [sys.argv[0], "0", "0"]
from force_probe import FF, Q, SLOT, LIM, LEOFF, CB, RW
sys.argv = sys.argv_save
from rlabel import relbyte
LEG = {tuple(map(int, l.split())) for l in open(R + "/work/grid/legal.txt")}
REGION = [(x, y) for x in range(30, 42) for y in range(24, 34) if (x, y) in LEG]
LIN = lambda b, l: l * 295 + (295 - b)
ELEM = {(SLOT[k][0], LEOFF[n] + ((1 - SLOT[k][1]) if (n // 2) % 2 else SLOT[k][1])) for n in LEOFF for k in SLOT}
ELEM |= {tuple(b) for e in LIM.values() for b in e["bits"]}


def elem_positions(x, y):
    """Absolute element-plane positions of LAB (x, y)."""
    out = set()
    hb, lane = RW[y]
    for df in range(-14, 26):
        for db in range(0, 70):
            if (df, db) in ELEM or df in (-1, 8, 9, 11):
                byte, ln = relbyte(hb, lane, db)
                out.add((CB[x] + df, byte, ln))
    return out


def design(d, S, D, sn, with_src):
    os.makedirs(d, exist_ok=True)
    v = ["module top(input clk, input din, input dt, output y);", "  wire c, q, w;"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din",
         "set_location_assignment PIN_T8 -to dt", "set_location_assignment PIN_A15 -to y",
         f"set_location_assignment LCCOMB_X{D[0]}_Y{D[1]}_N0 -to ld"]
    if with_src:
        v += ["  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
              "  " + FF.format(n="rs", d="c", q="q")]
        q += [f"set_location_assignment LCCOMB_X{S[0]}_Y{S[1]}_N{sn} -to ls", f"set_location_assignment FF_X{S[0]}_Y{S[1]}_N{sn + 1} -to rs"]
    v += [f"  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab({'q' if with_src else chr(49) + chr(39) + 'b0'}),.datac(1'b0),.datad(1'b0),.combout(w));",
          "  assign y = w;", "endmodule"]
    open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")


def build(d, rcf=False):
    if not os.path.exists(d + "/top.rbf"):
        if subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True).returncode:
            return False
        if rcf:
            subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=d, capture_output=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
    return True


def run(k):
    rnd = random.Random(k)
    S, D = rnd.sample(REGION, 2)
    sn = rnd.randrange(2, 32, 2)
    d = f"{R}/work/wh_{k:04d}"
    if os.path.exists(d + "/result.json"):
        return json.load(open(d + "/result.json"))
    design(d, S, D, sn, True); design(d + "/base", S, D, sn, False)
    if not (build(d, rcf=True) and build(d + "/base")):
        return None
    blk = re.search(r"signal_name = rs \{(.*?)\n\}", open(d + "/top.rcf").read(), re.S)
    route = re.findall(r"(\w+):X(\d+)Y(\d+)S0I(\d+);", blk.group(1)) if blk else []
    a, b = open(d + "/base/top.rbf", "rb").read(), open(d + "/top.rbf", "rb").read()
    excl = elem_positions(*S) | elem_positions(*D)
    on = []
    for f in range(NFRAMES):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            x = (b[o + byte] & ~a[o + byte]) & 0xFF
            for bit in range(8):
                if x >> bit & 1 and (f, byte, bit) not in excl:
                    on.append([f, byte, bit])
    res = {"k": k, "S": S, "D": D, "sn": sn, "route": [[t, int(x), int(y), int(i)] for t, x, y, i in route], "on": on}
    json.dump(res, open(d + "/result.json", "w"))
    return res


REL = os.environ.get("REL", "1") == "1"


def colbase(x):
    """Stable per-column anchor frame (real LAB column base, else nearest lower LAB column + 35 per step)."""
    if x in CB:
        return CB[x]
    lo = max([c for c in CB if c < x] or [min(CB)])
    return CB[lo] + 35 * (x - lo)


def rowlin(y):
    """Stable per-row anchor (row-linear byte of the row's high byte; outside rows extrapolated)."""
    if y in RW:
        return LIN(*RW[y])
    return LIN(*RW[max(1, min(33, y))]) + 70 * (y - max(1, min(33, y)))


def hop_keys(route):
    """Consecutive hops. REL: keyed by the destination element's column x and row phase y%4, with the source
    as an offset: "C4:11@0,-1>LOCAL_INTERCONNECT:3|x38p3". Absolute otherwise."""
    if not REL:
        return [f"{a[0]}:{a[1]},{a[2]},{a[3]}>{b[0]}:{b[1]},{b[2]},{b[3]}" for a, b in zip(route, route[1:])]
    return [f"{a[0]}:{a[3]}@{a[1]-b[1]},{a[2]-b[2]}>{b[0]}:{b[3]}|x{b[1]}p{b[2] % 4}" for a, b in zip(route, route[1:])]


def to_rel(route, bits):
    """Per hop: the route's on-bits relative to the hop's destination element (df, db) for REL keying."""
    out = []
    for a, b in zip(route, route[1:]):
        x, y = b[1], b[2]
        out.append({(f - colbase(x), LIN(byte, bit) - rowlin(y)) for f, byte, bit in bits})
    return out


def solve(results):
    """Per-hop code (relative to the hop's destination element): bits common to every route containing the
    hop, minus bits explained by the other hops' codes in that route (iterated)."""
    occ = collections.defaultdict(list)            # hop -> [(result, hop index)]
    for r in results:
        for i, h in enumerate(hop_keys(r["route"])):
            occ[h].append((r, i))
    rel = {id(r): to_rel(r["route"], r["on"]) for r in results}
    code = {}
    for _ in range(4):
        for h, rs in occ.items():
            sets = []
            for r, i in rs:
                hk = hop_keys(r["route"]); rr = rel[id(r)]
                mine = rr[i]
                # bits explained by other hops, translated into this hop's frame of reference
                route = r["route"]; bx, by = route[i + 1][1], route[i + 1][2]
                for j, h2 in enumerate(hk):
                    if j != i and h2 in code:
                        ox, oy = route[j + 1][1], route[j + 1][2]
                        dfo = colbase(ox) - colbase(bx)
                        dbo = rowlin(oy) - rowlin(by)
                        mine = mine - {(df + dfo, db + dbo) for df, db in code[h2]}
                sets.append(mine)
            code[h] = set.intersection(*sets) if sets else set()
    return code, occ


if __name__ == "__main__":
    if sys.argv[1:] == ["solve"]:
        allr = [json.load(open(p)) for p in sorted(__import__("glob").glob(R + "/work/wh_*/result.json"))]
        rnd = random.Random(0); rnd.shuffle(allr)
        cut = int(len(allr) * 0.8)
        train, test = allr[:cut], allr[cut:]
        code, occ = solve(train)
        # hold-out: predicted = union of known hop codes; compare with the measured on-bits
        tp = fp = fn = cov = 0
        for r in test:
            hs = hop_keys(r["route"])
            if not all(h in code for h in hs):
                continue
            cov += 1
            route = r["route"]
            pred = set()
            for i, h in enumerate(hs):
                x, y = route[i + 1][1], route[i + 1][2]
                for df, db in code[h]:
                    L = rowlin(y) + db                     # row-linear position -> (byte, lane)
                    ln, rem = divmod(L, 295)
                    pred.add((colbase(x) + df, 295 - rem, ln))
            meas = {tuple(p) for p in r["on"]}
            tp += len(pred & meas); fp += len(pred - meas); fn += len(meas - pred)
        print(f"designs {len(allr)} (train {len(train)}, test {len(test)}); hops decoded {len(code)}")
        print(f"hold-out: {cov}/{len(test)} test routes fully covered; bits right {tp}, extra {fp}, missing {fn}")
        kinds = collections.Counter(h.split(":")[0] + ">" + h.split(">")[1].split(":")[0] for h in code)
        print("hop kinds:", dict(kinds))
        # final tables from ALL designs; a hop needs >= MINOCC occurrences to be trusted for routing
        code, occ = solve(allr)
        MINOCC = int(os.environ.get("MINOCC", "2"))
        trusted = {h: c for h, c in code.items() if len(occ[h]) >= MINOCC}
        print("hops seen >=", MINOCC, "times:", len(trusted), "of", len(code))
        json.dump({h: sorted(list(map(list, c))) for h, c in trusted.items()}, open(R + "/fuzz/wire_hops.json", "w"), indent=0)
        chains = [r["route"] for r in allr if r["route"] and all(h in trusted for h in hop_keys(r["route"])
                  if not (h.startswith("LE_BUFFER") and ">LOCAL_INTERCONNECT" in h))]
        uniq = {json.dumps(c): c for c in chains}
        json.dump(list(uniq.values()), open(R + "/fuzz/wire_chains.json", "w"), indent=0)
        print("decoded routes for the router:", len(uniq))
    else:
        s0, n = int(os.environ.get("SEED0", "0")), int(os.environ.get("N", "200"))
        with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
            for r in ex.map(run, range(s0, s0 + n)):
                if r:
                    print(r["k"], r["S"], r["D"], len(r["route"]), "hops,", len(r["on"]), "bits", flush=True)
