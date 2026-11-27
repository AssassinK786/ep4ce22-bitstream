#!/usr/bin/env python3
"""DE0-Nano blinky RBF from decoded models (v2; v1 kept as blinky_gen_v1.py).

Baseline: an "empty device", the bitwise majority of three trivial pin-to-pin designs with
disjoint pins and paths (work/bl_e1..e3): no design's own bits survive the vote.
Models applied, by group (each checked bit by bit against the Quartus build work/bl_full):
  LUT     LUT masks (post-fit .vo) at the slot/column/row positions (lut_slots, lab_grid)
  OUTSEL  per-LE local-output driver select (fuzz/ff_db2.json; 1 = comb, 0 = reg)
  LIM     LUT-input mux codes (fuzz/lim_codes_ll.json: lim_codes + LOCAL_LINE feedback codes;
          a source missing for one slot takes the same port's code from the other slots)
  PIN     per-pin I/O bits (fuzz/pins.json) for the pins the design uses
  CLOCK   clock chain and per-LAB clock bits (fuzz/clock.json)
  ROUTE   decoded path entries for routes outside the LABs (fuzz/paths.json)
Whatever still differs from Quartus is copied as measured and reported per group.
Output: work/blinky_ours.rbf (with copied bits), work/blinky_model_only.rbf, report json.
"""
import os, re, sys, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import Rbf, F0, FLEN, NFRAMES, PERIPH, PERIPH_LEN, SIZE
from rlabel import src_label, relbyte

G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}
RW = {int(k): tuple(v) for k, v in G["row"].items()}
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
LIM = json.load(open(R + "/fuzz/lim_codes_ll.json"))
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}
def opt(name):
    p = R + "/fuzz/" + name
    return json.load(open(p)) if os.path.exists(p) else None
PINS, CLOCK, PATHS = opt("pins.json"), opt("clock.json"), opt("paths.json")  # paths: fuzz_vote.py

# ---- baseline: bitwise majority of three trivial designs
E = [open(R + f"/work/bl_e{i}/top.rbf", "rb").read() for i in (1, 2, 3)]
base = Rbf(bytes((a & b) | (a & c) | (b & c) for a, b, c in zip(*E)))
base.fix_crcs()
DESIGN = os.environ.get("DESIGN", "bl_full")
qrt = Rbf.load(R + f"/work/{DESIGN}/top.rbf")
d = R + f"/work/{DESIGN}"


def absbit(x, y, df, db, dl=0):
    hb, lane = RW[y]
    byte, ln = relbyte(hb, lane, db)
    return CB[x] + df, byte, ln + dl


def get(r, f, byte, bit):
    return (r.d[F0 + FLEN * f + byte] >> bit) & 1


model = {}
def put(pos, val, src):
    if pos in model and model[pos][0] != val:
        print("conflict", pos, model[pos], val, src)
    model[pos] = (val, src)

# ---- design facts from Quartus's report files (placement, masks, routing)
place = {}
for l in open(d + "/extra.qsf"):
    m = re.match(r"set_location_assignment (LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+) -to (\S+)", l)
    if m:
        place[m[5]] = (m[1], int(m[2]), int(m[3]), int(m[4]))
vo = open(d + "/simulation/modelsim/top.vo").read()
masks = {m[1]: int(m[2], 16) for m in re.finditer(r"defparam \\?(\w+)\s*\.lut_mask = 16'h([0-9A-Fa-f]+);", vo)}
pips = json.load(open(d + "/pips.json"))

# ---- LUT
for name, (kind, x, y, n) in place.items():
    if kind == "LCCOMB":
        m = masks[name]
        mirror = (n // 2) % 2 == 1
        for k in range(16):
            df, db = SLOT[k]
            db = (1 - db) if mirror else db
            put(absbit(x, y, df, LEOFF[n] + db), (m >> k) & 1, "LUT")

# ---- OUTSEL: local-output driver select, from the routing hops out of each LE
local = {}
for a, b in pips:
    m = re.match(r"(FF|LCCOMB)_X(\d+)_Y(\d+)_N(\d+)$", a)
    if m and b.startswith("LOCAL_LINE"):
        n = int(m[4]) - (1 if m[1] == "FF" else 0)
        local[(int(m[2]), int(m[3]), n)] = "reg" if m[1] == "FF" else "comb"
FFCLK = {}
for a, b in pips:
    m = re.match(r"FF_X(\d+)_Y(\d+)_N(\d+)\.clk$", b)
    if m:
        FFCLK[(int(m[1]), int(m[2]), int(m[3]))] = re.sub(r"_X\d+_Y\d+_N0", "", a)
FFCLK_LAB = collections.defaultdict(set)
for (x_, y_, n_), s_ in FFCLK.items():
    FFCLK_LAB[(x_, y_)].add(s_)
# FF used: (11, b) = 1 per LE with a register (fuzz_vote2.py; positions = old ff_db "(11, b)")
FFDB_OLD = json.load(open(R + "/fuzz/ff_db.json"))
ff_to_buf = {re.match(r"FF_X(\d+)_Y(\d+)_N(\d+)$", a).groups() for a, b in pips
             if re.match(r"FF_X\d+_Y\d+_N\d+$", a) and b.startswith("LE_BUFFER")}
for name, (kind, x, y, n) in place.items():
    if kind == "FF":
        for df, db, dl in FFDB_OLD["le"][f"N{n-1}"]["ff_used"]:
            if df == 11:                       # (11, b): the FF drives the LE_BUFFER (feat analysis, ~96 %)
                # (11, b): clock-pair select. 0 when the FF is clocked straight from BLK_CLK_BUF in a LAB
                # where some FF uses the LAB_CONTROL_MUX clock; otherwise 1 (training data, ~97 %).
                srcs_ = FFCLK_LAB.get((x, y), set()); mine = FFCLK.get((x, y, n))
                v_ = 0 if (mine or "").startswith("BLK_CLK_BUF") and any(t.startswith("LAB_CONTROL_MUX") for t in srcs_) else 1
                put(absbit(x, y, df, db, dl), v_, "FFUSED")
            if df == 8:
                pass
for (x, y, n), src in local.items():
    db = LEOFF[n] + (1 if (n // 2) % 2 == 0 else 0)
    put(absbit(x, y, 9, db), 1 if src == "comb" else 0, "OUTSEL")

# ---- LIM (with slot fallback per port)
LUTREL = {(SLOT[k][0], LEOFF[n] + (1 - SLOT[k][1] if (n // 2) % 2 else SLOT[k][1])) for n in LEOFF for k in SLOT}
def code_for(n, port, lab):
    e = LIM.get(f"N{n}.{port}")
    if e and lab in e["codes"]:
        return e["bits"], e["codes"][lab], "LIM"
    alt = collections.Counter(L["codes"][lab] for k, L in LIM.items()
                              if k.endswith("." + port) and lab in L["codes"] and e and len(L["bits"]) == len(e["bits"]))
    if alt:
        return e["bits"], alt.most_common(1)[0][0], "LIM-slot"
    return None
nolim = []
for a, b in pips:
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$", b)
    if not m:
        continue
    x, y, n, port = int(m[1]), int(m[2]), int(m[3]), m[4]
    r = code_for(n, port, src_label(a, x, y))
    if r is None:
        nolim.append((b, src_label(a, x, y)))
        continue
    bits, code, tag = r
    for (df, db), c in zip(bits, code):
        if (df, db) in LUTREL:          # a LUT-content position is never a mux bit
            continue
        put(absbit(x, y, df, db), int(c), tag)

# ---- PIN, CLOCK, ROUTE tables (absolute positions; periphery bytes separately)
periph_model = {}
def apply_table(entries, tag):
    for e in entries:
        if e[0] == "cram":
            put(tuple(e[1:4]), e[4], tag)
        else:                                   # ("periph", logical byte index, value)
            periph_model[e[1]] = (e[2], tag)
used_pins = {"A15": "out", "R8": "clk"}
if PINS:
    for p, use in used_pins.items():
        if p in PINS and use in PINS[p]:
            apply_table(PINS[p][use], "PIN")
if CLOCK:
    apply_table(CLOCK["chain"], "CLOCK")
    for (x, y) in {(v[1], v[2]) for v in place.values() if v[0] == "FF"}:
        # CLOCK["lab"] held (11, -2) = 1: that is N0's clock-pair select, now set by the (11, b) rule
        pass
TREE = opt(os.environ.get("TREE", "clock_tree.json"))
if TREE:
    for _k, _t in TREE.items():
        apply_table(_t, "CLOCK-tree")
if PATHS:
    for key in PATHS:
        apply_table(PATHS[key], "ROUTE")

# ---- LAB features (fuzz/feat_bits.json) and local-line driver tables (fuzz/li_joint.json)
FEAT, LIJ = opt("feat_bits.json"), opt("li_joint.json")
labfeat = collections.defaultdict(set); labline = collections.defaultdict(dict)
for a, b in pips:
    for node in (a, b):
        m = re.match(r"(LE_BUFFER|LOCAL_INTERCONNECT|LOCAL_LINE|BLK_CLK_LIM|BLK_CLK_BUF|LAB_CLK|LAB_CONTROL_MUX)_X(\d+)_Y(\d+)_N0_I(\d+)", node)
        if m:
            labfeat[(int(m[2]), int(m[3]))].add(f"{m[1]}_I{m[4]}")
        m = re.match(r"FF_X(\d+)_Y(\d+)_N(\d+)", node)
        if m:
            labfeat[(int(m[1]), int(m[2]))].add(f"FF_N{m[3]}")
    m = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", b)
    if m:
        labline[(int(m[1]), int(m[2]))][int(m[3])] = src_label(a, int(m[1]), int(m[2]))
for name, (kind, x, y, n) in place.items():          # FFs from the placement too (STA may omit one)
    if kind == "FF":
        labfeat[(x, y)].add(f"FF_N{n}")
used_labs = {(v[1], v[2]) for v in place.values()}
_LIS0 = opt("li_struct.json") or {}
STRUCT_LINES = {lab: {k for k, s_ in labline[lab].items() if f"{k}|{s_}" in _LIS0} for lab in labline}
# per LE: (-1, x) = LE used (any output used); (8, a) = combout drives the LE_BUFFER
c2buf = {(int(m[1]), int(m[2]), int(m[3])) for a, b in pips for m in [re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)$", a)]
         if m and b.startswith("LE_BUFFER")}
FM1 = {int(v["feature"][4:]) - 1: int(k.split(",")[1]) for k, v in (FEAT or {}).items()
       if v["feature"].startswith("FF_N") and k.startswith("-1,")}
for name, (kind, x, y, n) in place.items():
    if kind == "LCCOMB":
        put(absbit(x, y, -1, LEOFF[n] + (1 if (n // 2) % 2 == 0 else 0)), 1, "LEUSED")
# combout -> LE_BUFFER_I<m> (LE n owns buffers n, n+1): bit (8, LEOFF[n] + m - n) = 1 (fuzz_vote3.py)
for a, b in pips:
    m1 = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)$", a); m2 = re.match(r"LE_BUFFER_X(\d+)_Y(\d+)_N0_I(\d+)$", b)
    if m1 and m2:
        x, y, n, m = int(m1[1]), int(m1[2]), int(m1[3]), int(m2[3])
        off = (m - n) if (n // 2) % 2 else 1 - (m - n)     # even pair members are mirrored (as the LUT slots)
        put(absbit(x, y, 8, LEOFF[n] + off), 1, "C2BUF")
for (x, y) in used_labs:
    for key, e in (FEAT or {}).items():
        if e["feature"].startswith("FF_N"):
            continue                                 # replaced by the LE-used rule above
        df, db = map(int, key.split(","))
        if not 0 <= db < 70:                         # another LAB's rows
            continue
        present = e["feature"] in labfeat[(x, y)]
        put(absbit(x, y, df, db), int(present) ^ int(e["inverted"]), "FEAT")
    for key, e in (LIJ or {}).items():
        df, db = map(int, key.split(","))
        if not 0 <= db < 70:
            continue
        if any(l in STRUCT_LINES.get((x, y), ()) for l in e["lines"]) or df in (-1, 8, 9, 11):
            continue                                 # element-plane frames belong to the per-LE rules                                 # a structural code exists for that line
        k = "|".join(labline[(x, y)].get(l, "-") for l in e["lines"])
        if k in e["table"]:
            put(absbit(x, y, df, db), e["table"][k], "LI")

# LAB with clocked FFs: (-21, 64) = 0 (1 in an empty device; 0 in 1096/1147 clocked LABs of the training data)
for (x, y) in {(v[1], v[2]) for v in place.values() if v[0] == "FF"}:
    put(absbit(x, y, -21, 64), 0, "LABCLK")
# LAB clock line i: direct FF clocking from BLK_CLK_BUF_I<i> sets (-17, 30+i) without, (-18, 30+i) with the
# clock also entering a local line (BLK_CLK_LIM_I<i>); neither when no FF is clocked directly.
for (x, y) in used_labs:
    for i in range(6):
        direct = any(s_ == f"BLK_CLK_BUF_I{i}" for (x_, y_, n_), s_ in FFCLK.items() if (x_, y_) == (x, y))
        lim = f"BLK_CLK_LIM_I{i}" in labfeat[(x, y)]
        if direct or lim or f"BLK_CLK_BUF_I{i}" in labfeat[(x, y)]:
            for df, v in ((-17, int(direct and not lim)), (-18, int(direct and lim))):
                model.pop(absbit(x, y, df, 30 + i), None)
                put(absbit(x, y, df, 30 + i), v, "LABCLKSEL")
LIOR = opt("li_or.json")
for (x, y) in used_labs:
    for key, Sb in (LIOR or {}).items():
        df, db = map(int, key.split(","))
        if not 0 <= db < 70:
            continue
        if df in (-1, 8, 9, 11) or any(k in STRUCT_LINES.get((x, y), ()) for k, s in Sb if labline[(x, y)].get(k) == s):
            continue                                 # the active term is covered by a structural code
        put(absbit(x, y, df, db), int(any(labline[(x, y)].get(k) == s for k, s in Sb)), "LI-OR")

LIS = opt("li_struct.json")            # structural (line, source) codes from .rcf experiments (li_struct.py)
GROUP = collections.defaultdict(set)        # line -> every position any known source code of it uses
for key, bits_ in (LIS or {}).items():
    GROUP[int(key.split("|")[0])] |= {(df, db) for df, db, v in bits_}
for (x, y) in used_labs:
    for k, src_ in labline[(x, y)].items():
        for df, db, v in (LIS or {}).get(f"{k}|{src_}", []):   # codes may reach into the neighbouring rows
            model.pop(absbit(x, y, df, db), None)
            put(absbit(x, y, df, db), v, "LI-S")

# inter-LAB wire chains (fuzz/wire_codes.json, tools/force3_probe.py): LE_BUFFER -> wire -> LOCAL_INTERCONNECT
WIRES = opt("wire_codes.json") or []
_hop = {}
for a, b in pips:
    _hop.setdefault(b, []).append(a)
def _rel(node, x, y):
    m = re.match(r"(\w+?)_X(\d+)_Y(\d+)_N0_I(\d+)$", node)
    return [m[1], int(m[2]) - x, int(m[3]) - y, int(m[4])] if m else None
for b, srcs_ in _hop.items():
    m = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I\d+$", b)
    if not m:
        continue
    x, y = int(m[1]), int(m[2])
    for w in srcs_:
        for d0 in _hop.get(w, []):
            chain = [_rel(d0, x, y), _rel(w, x, y), _rel(b, x, y)]
            for e in WIRES:
                if e["chain"] == chain:
                    for df, db, v in e["bits"]:
                        model.pop(absbit(x, y, df, db), None)
                        put(absbit(x, y, df, db), v, "WIRE")

# absolute inter-LAB wire hops (tools/wire_harvest.py -> fuzz/wire_hops.json, via tools/routing_model.py)
from routing_model import RoutingModel as _RM
_rm = _RM()
for a, b in pips:
    if any(t in a or t in b for t in ("R4_", "C4_", "R24_", "C16_")):
        r_ = _rm.wire_hop(a, b)
        for pos_, v_ in (r_ or {}).items():
            put(pos_, v_, "WIREHOP")

# vertical column chains (tools/col_vert.py -> fuzz/col_vert_<x>.json): code of a whole LE_BUFFER -> C4.. ->
# LOCAL_INTERCONNECT chain, relative to the destination LAB, valid for that column and row phase (y % 4)
import glob as _glob
COLV = [e for f_ in _glob.glob(R + "/fuzz/col_vert_*.json") for e in json.load(open(f_))
        if not (os.environ.get("PNR_VALIDATED_ONLY") and e.get("validated") is False)]
_into = collections.defaultdict(list)
for a, b in pips:
    _into[b].append(a)
_NODE = re.compile(r"(\w+?)_X(\d+)_Y(\d+)_N0_I(\d+)$")
for b in list(_into):
    mb = _NODE.match(b)
    if not mb or mb[1] != "LOCAL_INTERCONNECT":
        continue
    x, y = int(mb[2]), int(mb[3])
    chain, cur = [[mb[1], 0, 0, int(mb[4])]], b
    while True:
        srcs = [s_ for s_ in _into.get(cur, []) if _NODE.match(s_)]
        if not srcs:
            break
        cur = srcs[0]; mm = _NODE.match(cur)
        chain.insert(0, [mm[1], int(mm[2]) - x, int(mm[3]) - y, int(mm[4])])
        if mm[1] == "LE_BUFFER":
            break
    for e in COLV:
        if e["x"] == x and e["phase"] in (None, y % 4) and e["chain"] == chain:
            for df, db in e["bits"]:
                model.pop(absbit(x, y, df, db), None)
                put(absbit(x, y, df, db), 1, "COLV")

# ---- check, assemble, residual
score = collections.Counter()
wrongs = collections.defaultdict(list)
for pos, (val, src) in model.items():
    ok = get(qrt, *pos) == val
    score[(src, ok)] += 1
    if not ok:
        wrongs[src].append((pos, val))
out = Rbf(base.d)
for (f, byte, bit), (val, _) in model.items():
    o = F0 + FLEN * f + byte
    out.d[o] = (out.d[o] & ~(1 << bit)) | (val << bit)
for i, (val, _) in periph_model.items():
    out.d[PERIPH + 4 * i:PERIPH + 4 * i + 4] = bytes([val]) * 4
mo = Rbf(out.d); mo.fix_crcs()
mo_cram = sum(bin(mo.d[F0 + FLEN * f + b] ^ qrt.d[F0 + FLEN * f + b]).count("1") for f in range(NFRAMES) for b in range(1, 296))
mo_per = sum(1 for k in range(PERIPH_LEN // 4) if mo.d[PERIPH + 4 * k] != qrt.d[PERIPH + 4 * k])
mo_identical = bytes(mo.d) == bytes(qrt.d)
mo.save(R + ("/work/blinky_model_only.rbf" if DESIGN == "bl_full" else f"/work/{DESIGN}_model_only.rbf"))

resid = collections.Counter()
rpos = []
for f in range(NFRAMES):
    o = F0 + FLEN * f
    for byte in range(1, 296):
        x = out.d[o + byte] ^ qrt.d[o + byte]
        for bit in range(8):
            if x >> bit & 1:
                p = (f, byte, bit)
                resid[model[p][1] + "-wrong" if p in model else "not-modelled"] += 1
                rpos.append(p)
        out.d[o + byte] = qrt.d[o + byte]
hdr = sum(1 for i in range(33, 73) if out.d[i] != qrt.d[i])
per = sum(1 for i in range(PERIPH, PERIPH + PERIPH_LEN, 4) if out.d[i] != qrt.d[i])
out.d[:F0] = qrt.d[:F0]
out.fix_crcs()
same = bytes(out.d) == bytes(qrt.d)
out.save(R + ("/work/blinky_ours.rbf" if DESIGN == "bl_full" else f"/work/{DESIGN}_ours.rbf"))

# classify unmodelled residual: inside a used LAB's window or elsewhere
labs = {(v[1], v[2]) for v in place.values()}
def where(p):
    f, byte, bit = p
    for (x, y) in labs:
        if CB[x] - 14 <= f <= CB[x] + 25:
            hb, lane = RW[y]
            lin = lambda b, l: l * 294 + (295 - b)
            if -8 <= lin(byte, bit) - lin(hb, lane) <= 80:
                return f"LAB {x},{y}"
    return "outside LABs"
cls = collections.Counter(where(p) for p in rpos)
rep = {
    "model_check": {f"{s}_{'ok' if ok else 'wrong'}": c for (s, ok), c in sorted(score.items())},
    "lut_inputs_without_code": nolim,
    "wrong": {k: v[:20] for k, v in wrongs.items()},
    "residual_cram_bits_copied": dict(resid),
    "residual_by_area": dict(cls),
    "periphery_logical_bytes_copied": per,
    "header_bytes_copied": hdr,
    "byte_identical_to_quartus": same,
    "model_only": {"cram_bits_differ": mo_cram, "periph_logical_bytes_differ": mo_per, "byte_identical_to_quartus": mo_identical},
}
json.dump({**rep, "residual_positions": rpos}, open(R + f"/work/{DESIGN}_gen_report.json", "w"), indent=1)
print(json.dumps(rep, indent=1))
