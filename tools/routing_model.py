#!/usr/bin/env python3
"""routing_model: CRAM bits for logic and routing on the EP4CE22 (DE0-Nano), from the decoded tables.

Stable API (used by tools/pnr/). Positions are absolute CRAM bits (frame, byte, bit) as in tools/rbf.py;
every function returns {position: value}. Node names follow Quartus's timing / .rcf naming:
  "LCCOMB_X<x>_Y<y>_N<n>.data[abcd]", "FF_X<x>_Y<y>_N<n>", "LE_BUFFER_X<x>_Y<y>_N0_I<m>",
  "LOCAL_INTERCONNECT_X<x>_Y<y>_N0_I<k>", "LOCAL_LINE_X<x>_Y<y>_N0_I<k>", "R4_/C4_/R24_/C16_X.._Y.._N0_I<i>".

  m = RoutingModel()
  m.lut(x, y, n, mask16)                 LUT contents of LE n (physical mask, inputs a..d = physical pins)
  m.lut_input(dst, src)                  LUT-input mux: dst "LCCOMB_X_Y_Nn.datab", src node driving it
  m.local_line(x, y, k, src)             LAB local line k driven by src (structural table)
  m.wire_chain(buf, wire, line)          LE_BUFFER -> R4/C4 -> LOCAL_INTERCONNECT chain (wire table)
  m.wire_hop(a, b)                       one inter-LAB hop with an absolute decoded code (fuzz/wire_hops.json,
                                         tools/wire_harvest.py): LE_BUFFER->wire, wire->wire, wire->line
  m.hops_to_bits(hops)                   [(a, b), ...] -> ({pos: val}, [unknown hops])
Element-plane rules (LE used, output selects, clock selects) need the whole LAB and stay in
tools/blinky_gen.py for now; hops_to_bits covers routing. Tables: fuzz/lut_slots.json, lab_grid.json,
lim_codes_ll.json, li_struct.json, wire_codes.json. Unknown = not decoded yet: never guessed.
"""
import os, re, sys, json, collections
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rlabel import src_label, relbyte

LEOFF = {0: 0, 2: 2, 4: 8, 6: 10, 8: 16, 10: 18, 12: 24, 14: 26, 16: 38, 18: 40, 20: 46, 22: 48,
         24: 54, 26: 56, 28: 62, 30: 64}
NODE = re.compile(r"^(\w+?)_X(\d+)_Y(\d+)_N(\d+)(?:_I(\d+))?(?:\.(\w+))?$")


def _load(name):
    p = os.path.join(R, "fuzz", name)
    return json.load(open(p)) if os.path.exists(p) else None


class RoutingModel:
    def __init__(self):
        g = _load("lab_grid.json")
        self.CB = {int(k): v for k, v in g["col"].items()}
        self.RW = {int(k): tuple(v) for k, v in g["row"].items()}
        self.SLOT = {int(k): tuple(v) for k, v in _load("lut_slots.json").items()}
        self.LIM = _load("lim_codes_ll.json")
        self.LIS = _load("li_struct.json") or {}
        self.WIRES = _load("wire_codes.json") or []
        self.HOPS = _load("wire_hops.json") or {}
        import glob as _g
        self.COLV = [e for f in _g.glob(os.path.join(R, "fuzz", "col_vert_*.json")) for e in json.load(open(f))]
        self.LUTREL = {(self.SLOT[k][0], LEOFF[n] + ((1 - self.SLOT[k][1]) if (n // 2) % 2 else self.SLOT[k][1]))
                       for n in LEOFF for k in self.SLOT}

    def pos(self, x, y, df, db):
        """Absolute (frame, byte, bit) of LAB-relative (df, db)."""
        hb, lane = self.RW[y]
        byte, ln = relbyte(hb, lane, db)
        return self.CB[x] + df, byte, ln

    def lut(self, x, y, n, mask):
        mirror = (n // 2) % 2 == 1
        out = {}
        for k in range(16):
            df, db = self.SLOT[k]
            out[self.pos(x, y, df, LEOFF[n] + ((1 - db) if mirror else db))] = (mask >> k) & 1
        return out

    def lut_input(self, dst, src):
        m = NODE.match(dst)
        x, y, n, port = int(m[2]), int(m[3]), int(m[4]), m[6]
        lab = src_label(src, x, y)
        e = self.LIM.get(f"N{n}.{port}")
        code = e["codes"].get(lab) if e else None
        if code is None and e:                     # same port, another slot (identical tables per port)
            alt = collections.Counter(L["codes"][lab] for k, L in self.LIM.items()
                                      if k.endswith("." + port) and lab in L["codes"] and len(L["bits"]) == len(e["bits"]))
            code = alt.most_common(1)[0][0] if alt else None
        if code is None:
            return None
        return {self.pos(x, y, df, db): int(c) for (df, db), c in zip(e["bits"], code) if (df, db) not in self.LUTREL}

    def local_line(self, x, y, k, src):
        bits = self.LIS.get(f"{k}|{src_label(src, x, y)}")
        return None if bits is None else {self.pos(x, y, df, db): v for df, db, v in bits}

    def wire_chain(self, buf, wire, line):
        m = NODE.match(line)
        x, y = int(m[2]), int(m[3])
        rel = lambda node: (lambda mm: [mm[1], int(mm[2]) - x, int(mm[3]) - y, int(mm[5])])(NODE.match(node))
        chain = [rel(buf), rel(wire), rel(line)]
        for e in self.WIRES:
            if e["chain"] == chain:
                return {self.pos(x, y, df, db): v for df, db, v in e["bits"]}
        for e in self.COLV:                        # column vertical chains (tools/col_vert.py), by row phase
            if e["x"] == x and e["phase"] in (None, y % 4) and e["chain"] == chain:
                return {self.pos(x, y, df, db): 1 for df, db in e["bits"]}
        return None

    @staticmethod
    def hop_key(a, b):
        f = lambda n: (lambda m: f"{m[1]}:{int(m[2])},{int(m[3])},{int(m[5])}")(NODE.match(n))
        return f"{f(a)}>{f(b)}"

    def wire_hop(self, a, b):
        """Absolute (frame, byte, bit) -> 1 for a decoded inter-LAB hop, or None."""
        try:
            bits = self.HOPS.get(self.hop_key(a, b))
        except TypeError:
            return None
        return None if bits is None else {tuple(p): 1 for p in bits}

    def hops_to_bits(self, hops):
        """hops: [(a, b)] as in Quartus timing reports. Returns ({pos: val}, [hops not encodable])."""
        bits, unknown = {}, []
        into = collections.defaultdict(list)
        for a, b in hops:
            into[b].append(a)
        for a, b in hops:
            r = None
            if b.startswith("LCCOMB") and "." in b and b.split(".")[1].startswith("data"):
                r = self.lut_input(b, a)
            elif b.startswith("LOCAL_INTERCONNECT"):
                m = NODE.match(b)
                x, y, k = int(m[2]), int(m[3]), int(m[5])
                if a.startswith(("R4_", "C4_", "R24_", "C16_")):
                    r = self.wire_hop(a, b)
                    if r is None:
                        srcs = into.get(a, [])
                        r = self.wire_chain(srcs[0], a, b) if srcs else None
                else:
                    r = self.local_line(x, y, k, a)
            elif b.startswith(("R4_", "C4_", "R24_", "C16_")) and a.startswith(("LE_BUFFER", "R4_", "C4_", "R24_", "C16_")):
                r = self.wire_hop(a, b)
                if r is None and a.startswith("LE_BUFFER"):
                    continue                        # may be encoded with the wire -> line hop (wire_chain)
            elif b.startswith(("LE_BUFFER", "LOCAL_LINE", "FF_")) or ".combout" in a or ".q" in a or b.endswith(".d"):
                continue                            # LE-internal / element-plane: per-LE rules
            if r is None:
                unknown.append((a, b))
            else:
                bits.update(r)
        return bits, unknown


if __name__ == "__main__":
    # self-check: encode a design's routing hops and compare with Quartus's build of it
    d = sys.argv[1] if len(sys.argv) > 1 else R + "/work/bl2_full"
    from rbf import Rbf, F0, FLEN
    m = RoutingModel()
    bits, unknown = m.hops_to_bits([tuple(h) for h in json.load(open(d + "/pips.json"))])
    q = Rbf.load(d + "/top.rbf")
    ok = sum(1 for (f, b, bit), v in bits.items() if ((q.d[F0 + FLEN * f + b] >> bit) & 1) == v)
    print(f"{d}: {len(bits)} routing bits, {ok} match Quartus, {len(bits) - ok} differ; {len(unknown)} hops not encodable")
    for h in unknown[:10]:
        print("  unknown:", h)
