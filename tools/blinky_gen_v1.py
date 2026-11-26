#!/usr/bin/env python3
"""DE0-Nano blinky RBF from our own bit models (tools/blinky_design.py placement).

Start: work/bl_empty/top.rbf (Quartus baseline: pin M1 -> pin L3 only, USERCODE fixed).
Apply, from decoded models only:
  LUT  - physical masks (post-fit .vo) at the slot/column/row positions of the LUT model
  FF   - fuzz/ff_db.json per-LE "ff_used" and LAB "ff_clock_on" bits (flipped from baseline)
  LIM  - fuzz/lim_codes.json LUT-input mux codes, sources from the STA routing (pips.json)
Then (not decoded yet, copied as measured from the Quartus build of the same design):
  everything else that differs: clock network, LAB clock, output buffer / C4 / IO-block
  routing, IOB and periphery settings, and clearing the baseline's own M1 -> L3 path.
Every model bit is checked against the Quartus build (work/bl_full/top.rbf).
Output: work/blinky_ours.rbf (+ report).
"""
import os, re, sys, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import Rbf, F0, FLEN, NFRAMES, PERIPH, PERIPH_LEN
from rlabel import src_label, relbyte

G = json.load(open(R + "/fuzz/lab_grid.json"))
CB = {int(k): v for k, v in G["col"].items()}
RW = {int(k): tuple(v) for k, v in G["row"].items()}
SLOT = {int(k): tuple(v) for k, v in json.load(open(R + "/fuzz/lut_slots.json")).items()}
FFDB = json.load(open(R + "/fuzz/ff_db.json"))
LIM = json.load(open(R + "/fuzz/lim_codes.json"))
# high byte of each LE's LUT pair below the row's high byte (from fuzz/le_geom.json, Y10)
LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}

base = Rbf.load(R + "/work/bl_empty/top.rbf")
qrt = Rbf.load(R + "/work/bl_full/top.rbf")
d = R + "/work/bl_full"


def absbit(x, y, df, db, dl=0):
    hb, lane = RW[y]
    byte, ln = relbyte(hb, lane, db)
    return CB[x] + df, byte, ln + dl


def get(r, f, byte, bit):
    return (r.d[F0 + FLEN * f + byte] >> bit) & 1


# ---- placement and masks
place = {}
for l in open(d + "/extra.qsf"):
    m = re.match(r"set_location_assignment (LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+) -to (\S+)", l)
    if m:
        place[m[5]] = (m[1], int(m[2]), int(m[3]), int(m[4]))
vo = open(d + "/simulation/modelsim/top.vo").read()
masks = {m[1]: int(m[2], 16) for m in re.finditer(r"defparam \\?(\w+)\s*\.lut_mask = 16'h([0-9A-Fa-f]+);", vo)}

model = {}                       # (frame, byte, bit) -> (value, source)
def put(pos, val, src):
    if pos in model and model[pos][0] != val:
        print("conflict", pos, model[pos], val, src)
    model[pos] = (val, src)

used_labs = set()
for name, (kind, x, y, n) in place.items():
    used_labs.add((x, y))
    if kind == "LCCOMB":
        m = masks[name]
        mirror = (n // 2) % 2 == 1
        for k in range(16):
            df, db = SLOT[k]
            db = (1 - db) if mirror else db
            put(absbit(x, y, df, LEOFF[n] + db), (m >> k) & 1, "LUT")
    else:
        le = FFDB["le"][f"N{n-1}"]
        for df, db, dl in le["ff_used"]:
            pos = absbit(x, y, df, db, dl)
            put(pos, 1 - get(base, *pos), "FF")
for x, y in used_labs:
    for df, db, dl in FFDB["lab"]["ff_clock_on"]:
        pos = absbit(x, y, df, db, dl)
        put(pos, 1 - get(base, *pos), "FF")

# ---- LUT-input muxes
pips = json.load(open(d + "/pips.json"))
nolim = []
for a, b in pips:
    m = re.match(r"LCCOMB_X(\d+)_Y(\d+)_N(\d+)\.(data[abcd])$", b)
    if not m:
        continue
    x, y, n, port = int(m[1]), int(m[2]), int(m[3]), m[4]
    e = LIM.get(f"N{n}.{port}")
    lab = src_label(a, x, y)
    if not e or lab not in e["codes"]:
        nolim.append((b, lab))
        continue
    for (df, db), c in zip(e["bits"], e["codes"][lab]):
        put(absbit(x, y, df, db), int(c), "LIM")

# ---- check against Quartus
score = collections.Counter()
wrong = collections.defaultdict(list)
for pos, (val, src) in model.items():
    ok = get(qrt, *pos) == val
    score[(src, ok)] += 1
    if not ok:
        wrong[src].append(pos)

out = Rbf(base.d)
for pos, (val, src) in model.items():
    f, byte, bit = pos
    o = F0 + FLEN * f + byte
    out.d[o] = (out.d[o] & ~(1 << bit)) | (val << bit)
# residual: bits where (baseline + model) still differs from Quartus -> copied as measured
resid = collections.Counter()
rlist = []
for f in range(NFRAMES):
    o = F0 + FLEN * f
    for byte in range(1, 296):
        x = out.d[o + byte] ^ qrt.d[o + byte]
        if x:
            for bit in range(8):
                if x >> bit & 1:
                    rlist.append((f, byte, bit))
                    resid["model-wrong" if (f, byte, bit) in model else "not modelled"] += 1
            out.d[o + byte] = qrt.d[o + byte]
per = sum(1 for i in range(PERIPH, PERIPH + PERIPH_LEN) if out.d[i] != qrt.d[i])
out.d[PERIPH:PERIPH + PERIPH_LEN] = qrt.d[PERIPH:PERIPH + PERIPH_LEN]
out.fix_crcs()
same = bytes(out.d) == bytes(qrt.d)
out.save(R + "/work/blinky_ours.rbf")
# also a model-only file (no residual) for inspection
mo = Rbf(base.d)
for (f, byte, bit), (val, _) in model.items():
    o = F0 + FLEN * f + byte
    mo.d[o] = (mo.d[o] & ~(1 << bit)) | (val << bit)
mo.fix_crcs(); mo.save(R + "/work/blinky_model_only.rbf")

total = sum(1 for f in range(NFRAMES) for byte in range(1, 296)
            for bit in range(8) if (base.d[F0 + FLEN * f + byte] ^ qrt.d[F0 + FLEN * f + byte]) >> bit & 1)
rep = {
    "cram_bits_baseline_vs_quartus": total,
    "model_bits_set": len(model),
    "model_check": {f"{s}_{'ok' if ok else 'wrong'}": c for (s, ok), c in sorted(score.items())},
    "model_wrong_positions": {k: v[:10] for k, v in wrong.items()},
    "lut_inputs_without_code": nolim,
    "residual_copied_as_measured": dict(resid),
    "periphery_bytes_copied": per,
    "byte_identical_to_quartus": same,
}
json.dump(rep, open(R + "/work/blinky_gen_report.json", "w"), indent=1)
print(json.dumps(rep, indent=1)[:3000])
# classify the residual by nearest structure
cls = collections.Counter()
for f, byte, bit in rlist:
    col = max((c for c in CB if CB[c] - 14 <= f), key=lambda c: CB[c], default=None)
    cls[col] += 1
print("residual by nearest LAB column:", dict(sorted(cls.items(), key=lambda t: (t[0] is None, t[0]))))
