#!/usr/bin/env python3
"""Vertical inter-LAB chains in one column (clean-room: Quartus in/out only).

record: natural single-net designs in column X: source FF at (X, ys, n) -> LUT (X, yd, N0).datab, |ys-yd| = 1..4.
        The .rcf route gives a chain; it is stored relative to the destination LAB.
force : every distinct relative chain is forced (edited .rcf, single branch, no route_port) at rows of the same
        yd % 4 phase; code = bits that are 1 in the forced build and 0 in a base without source/net, minus
        the element planes of the source and destination LABs, relative to the destination LAB.
        Entry kept if identical at the training rows; the last row is held out and predicted.
Output: fuzz/col_vert_<X>.json [{chain, phase, bits, rows_train, row_test, test_ok}]
usage: J=1 python3 tools/col_vert.py record|force [X]
"""
import os, sys, re, json, random, shutil, subprocess, collections, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from rbf import F0, FLEN, NFRAMES
from wire_harvest import design, build, elem_positions, LEG, LIN, CB, RW, Q
MODE = sys.argv[1]
X = int(sys.argv[2]) if len(sys.argv) > 2 else 38
ROWS = [y for y in range(1, 34) if (X, y) in LEG]


def rel(node, x, y):
    t, nx, ny, i = node
    return [t, int(nx) - x, int(ny) - y, int(i)]


def natural(ys, yd, sn):
    d = f"{R}/work/cv_{X}_{ys}_{yd}_{sn}"
    if not os.path.exists(d + "/route.json"):
        design(d, (X, ys), (X, yd), sn, True)
        if not build(d, rcf=True):
            return None
        blk = re.search(r"signal_name = rs \{(.*?)\n\}", open(d + "/top.rcf").read(), re.S)
        route = re.findall(r"(\w+):X(\d+)Y(\d+)S0I(\d+);", blk.group(1)) if blk else []
        json.dump(route, open(d + "/route.json", "w"))
    return json.load(open(d + "/route.json"))


def forced(chain, yd):
    """Force a dest-relative chain into destination (X, yd). Returns the code relative to (X, yd) or None."""
    b0 = chain[0]
    ys = yd + b0[2]; sn = b0[3] - b0[3] % 2
    if (X, ys) not in LEG:
        return None
    tag = f"cvf_{X}_{yd}_" + "_".join(f"{h[0][:2]}{h[1]}{h[2]}{h[3]}" for h in chain).replace("-", "m")
    d = f"{R}/work/{tag}"
    if os.path.exists(d + "/code.json"):
        return json.load(open(d + "/code.json"))
    nat = f"{R}/work/cv_{X}_{ys}_{yd}_{sn}"
    if natural(ys, yd, sn) is None:
        return None
    # rebuild the natural design with its database (build() removed it), then re-fit with the forced chain
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    design(d, (X, ys), (X, yd), sn, True)
    if subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True).returncode:
        return None
    subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=d, capture_output=True)
    rcf = open(d + "/top.rcf").read()
    blk = re.search(r"signal_name = rs \{.*?\n\}", rcf, re.S).group(0)
    els = "".join(f"\t{h[0]}:X{X + h[1]}Y{yd + h[2]}S0I{h[3]};\n" for h in chain)
    open(d + "/top.rcf", "w").write(rcf.replace(blk, "signal_name = rs {\n" + els + "\tdest = ( w, DATAB );\n}"))
    r = subprocess.run([Q + "/quartus_fit", "top"], cwd=d, capture_output=True, text=True)
    if "Error on line number" in r.stdout or r.returncode:
        json.dump(None, open(d + "/code.json", "w")); return None
    subprocess.run([Q + "/quartus_asm", "top"], cwd=d, capture_output=True)
    subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=d, capture_output=True)
    txt = open(d + "/top.rcf").read()
    if not all(f"{h[0]}:X{X + h[1]}Y{yd + h[2]}S0I{h[3]};" in txt for h in chain):
        json.dump(None, open(d + "/code.json", "w")); return None
    base = d + "/base"
    design(base, (X, ys), (X, yd), sn, False)
    build(base)
    a, b = open(base + "/top.rbf", "rb").read(), open(d + "/top.rbf", "rb").read()
    excl = elem_positions(X, ys) | elem_positions(X, yd)
    hb, lane = RW[yd]; L0 = LIN(hb, lane)
    code = []
    for f in range(CB[X] - 30, CB[X] + 45):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            on = (b[o + byte] & ~a[o + byte]) & 0xFF
            for bit in range(8):
                if on >> bit & 1 and (f, byte, bit) not in excl:
                    code.append([f - CB[X], LIN(byte, bit) - L0])
    code.sort()
    json.dump(code, open(d + "/code.json", "w"))
    for sub in ("db", "incremental_db", "base/db", "base/incremental_db"):
        shutil.rmtree(f"{d}/{sub}", ignore_errors=True)
    return code


def refit(src_dir, out_dir, chain, yd):
    """Copy a compiled design (with db + rcf), force the source net onto `chain`, re-fit + assemble."""
    shutil.rmtree(out_dir, ignore_errors=True); shutil.copytree(src_dir, out_dir)
    rcf = open(out_dir + "/top.rcf").read()
    blk = re.search(r"signal_name = rs \{.*?\n\}", rcf, re.S).group(0)
    els = "".join(f"\t{h[0]}:X{X + h[1]}Y{yd + h[2]}S0I{h[3]};\n" for h in chain)
    open(out_dir + "/top.rcf", "w").write(rcf.replace(blk, "signal_name = rs {\n" + els + "\tdest = ( w, DATAB );\n}"))
    r = subprocess.run([Q + "/quartus_fit", "top"], cwd=out_dir, capture_output=True, text=True)
    if "Error on line number" in r.stdout or r.returncode:
        return None
    subprocess.run([Q + "/quartus_asm", "top"], cwd=out_dir, capture_output=True)
    subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=out_dir, capture_output=True)
    txt = open(out_dir + "/top.rcf").read()
    if not all(f"{h[0]}:X{X + h[1]}Y{yd + h[2]}S0I{h[3]};" in txt for h in chain):
        return None
    return open(out_dir + "/top.rbf", "rb").read()


def forced_pair(chain, alts, yd):
    """Code of `chain` at destination row yd: one compile, re-fitted with an alternative chain (base) and with
    `chain` (variant); every other net keeps its .rcf route. Bits 1 in the variant and 0 in the base."""
    b0 = chain[0]; ys = yd + b0[2]; sn = b0[3] - b0[3] % 2
    if (X, ys) not in LEG:
        return None
    tag = f"cvp_{X}_{yd}_" + "_".join(f"{h[0][:2]}{h[1]}{h[2]}{h[3]}" for h in chain).replace("-", "m")
    d = f"{R}/work/{tag}"
    if os.path.exists(d + "/code.json"):
        return json.load(open(d + "/code.json"))
    os.makedirs(d, exist_ok=True)
    nat = d + "/nat"
    if not os.path.exists(nat + "/top.rcf"):
        design(nat, (X, ys), (X, yd), sn, True)
        if subprocess.run([R + "/tools/qcompile.sh", nat], capture_output=True).returncode:
            return None
        subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=nat, capture_output=True)
    var = refit(nat, d + "/var", chain, yd)
    code = None
    if var is not None:
        for alt in alts:
            base = refit(nat, d + "/base", alt, yd)
            if base is None:
                continue
            hb, lane = RW[yd]; L0 = LIN(hb, lane)
            code = []
            for f in range(CB[X] - 30, CB[X] + 45):
                o = F0 + FLEN * f
                for byte in range(1, 296):
                    on = (var[o + byte] & ~base[o + byte]) & 0xFF
                    for bit in range(8):
                        if on >> bit & 1:
                            code.append([f - CB[X], LIN(byte, bit) - L0])
            code.sort()
            break
    json.dump(code, open(d + "/code.json", "w"))
    for sub in ("nat/db", "nat/incremental_db", "var/db", "var/incremental_db", "base/db", "base/incremental_db"):
        shutil.rmtree(f"{d}/{sub}", ignore_errors=True)
    return code


def design2(d, ys, yd, sn, use):
    """Source FF (X, ys, sn+1) -> dest LUT (X, yd, N0).datab (if use) and -> dummy LUT (X, ys, N<sn+2 or sn-2>)."""
    os.makedirs(d, exist_ok=True)
    dn = sn + 2 if sn <= 28 else sn - 2
    v = ["module top(input clk, input din, input dt, output y, output z);", "  wire c, q, w, u;",
         "  cycloneive_lcell_comb #(.lut_mask(16'haaaa)) ls (.dataa(din),.datab(1'b0),.datac(1'b0),.datad(1'b0),.combout(c));",
         "  dffeas rs (.clk(clk),.d(c),.ena(1'b1),.clrn(1'b1),.prn(1'b1),.sclr(1'b0),.sload(1'b0),.asdata(1'b0),.q(q));",
         f"  cycloneive_lcell_comb #(.lut_mask(16'h6666)) ld (.dataa(dt),.datab({'q' if use else chr(49) + chr(39) + 'b0'}),.datac(1'b0),.datad(1'b0),.combout(w));",
         "  cycloneive_lcell_comb #(.lut_mask(16'h6666)) lu (.dataa(q),.datab(dt),.datac(1'b0),.datad(1'b0),.combout(u));",
         "  assign y = w;", "  assign z = u;", "endmodule"]
    q = ["set_location_assignment PIN_R8 -to clk", "set_location_assignment PIN_M1 -to din", "set_location_assignment PIN_T8 -to dt",
         "set_location_assignment PIN_A15 -to y", "set_location_assignment PIN_B13 -to z",
         f"set_location_assignment LCCOMB_X{X}_Y{ys}_N{sn} -to ls", f"set_location_assignment FF_X{X}_Y{ys}_N{sn + 1} -to rs",
         f"set_location_assignment LCCOMB_X{X}_Y{yd}_N0 -to ld", f"set_location_assignment LCCOMB_X{X}_Y{ys}_N{dn} -to lu"]
    open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")


def rs_branches(rcf):
    """The source net's block split into (elements text, dest line) branches."""
    body = re.search(r"signal_name = rs \{(.*?)\n\}", rcf, re.S).group(1)
    return [b.strip("\n") for b in re.split(r"\n\s*\n", body) if b.strip()]


def forced_iso(chain, yd):
    """Code of `chain` into (X, yd): variant (net through chain + dummy branch) vs base (same design with the
    dest input tied off, every other route pinned by the same .rcf). Bits 1 in variant, 0 in base."""
    b0 = chain[0]; ys = yd + b0[2]; sn = b0[3] - b0[3] % 2
    if (X, ys) not in LEG:
        return None
    tag = f"cvi_{X}_{yd}_" + "_".join(f"{h[0][:2]}{h[1]}{h[2]}{h[3]}" for h in chain).replace("-", "m")
    d = f"{R}/work/{tag}"
    if os.path.exists(d + "/code.json"):
        return json.load(open(d + "/code.json"))
    os.makedirs(d, exist_ok=True)
    nat = d + "/nat"
    design2(nat, ys, yd, sn, True)
    if subprocess.run([R + "/tools/qcompile.sh", nat], capture_output=True).returncode:
        json.dump(None, open(d + "/code.json", "w")); return None
    subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=nat, capture_output=True)
    rcf = open(nat + "/top.rcf").read()
    blk = re.search(r"signal_name = rs \{.*?\n\}", rcf, re.S).group(0)
    dummy = [b for b in rs_branches(rcf) if "( u," in b or "( u " in b]
    if not dummy or "label" in dummy[0] or "branch_point" in dummy[0]:
        json.dump(None, open(d + "/code.json", "w")); return None
    els = "".join(f"\t{h[0]}:X{X + h[1]}Y{yd + h[2]}S0I{h[3]};\n" for h in chain)
    var_blk = "signal_name = rs {\n" + els + "\tdest = ( w, DATAB );\n\n" + dummy[0] + "\n}"
    base_blk = "signal_name = rs {\n" + dummy[0] + "\n}"
    out = {}
    for name, blk2, use in (("var", var_blk, True), ("base", base_blk, False)):
        dd = d + "/" + name
        shutil.rmtree(dd, ignore_errors=True)
        if use:
            shutil.copytree(nat, dd)
        else:
            design2(dd, ys, yd, sn, False)
            subprocess.run([Q + "/quartus_map", "top"], cwd=dd, capture_output=True) if False else None
            shutil.copy(R + "/tools/qcompile.sh", dd + "/.q")       # (just a marker)
            # first compile normally to create the project, then re-fit with the pinned routing
            if subprocess.run([R + "/tools/qcompile.sh", dd], capture_output=True).returncode:
                json.dump(None, open(d + "/code.json", "w")); return None
        txt = rcf.replace(blk, blk2)
        if not use:                                   # ld has no datab net: drop nothing else
            pass
        open(dd + "/top.rcf", "w").write(txt)
        qsf = open(dd + "/top.qsf").read()
        if "ROUTING_BACK_ANNOTATION_FILE" not in qsf:
            open(dd + "/top.qsf", "a").write("set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL\nset_global_assignment -name ROUTING_BACK_ANNOTATION_FILE top.rcf\n")
        r = subprocess.run([Q + "/quartus_fit", "top"], cwd=dd, capture_output=True, text=True)
        if "Error on line number" in r.stdout or r.returncode:
            json.dump(None, open(d + "/code.json", "w")); return None
        subprocess.run([Q + "/quartus_asm", "top"], cwd=dd, capture_output=True)
        out[name] = open(dd + "/top.rbf", "rb").read()
    var, base = out["var"], out["base"]
    hb, lane = RW[yd]; L0 = LIN(hb, lane)
    excl = elem_positions(X, yd)
    code = []
    for f in range(CB[X] - 30, CB[X] + 45):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            on = (var[o + byte] & ~base[o + byte]) & 0xFF
            for bit in range(8):
                if on >> bit & 1 and (f, byte, bit) not in excl:
                    code.append([f - CB[X], LIN(byte, bit) - L0])
    code.sort()
    json.dump(code, open(d + "/code.json", "w"))
    for sub in ("nat", "var", "base"):
        for s_ in ("db", "incremental_db"):
            shutil.rmtree(f"{d}/{sub}/{s_}", ignore_errors=True)
    return code


def nat_iso(ys, yd, sn):
    """Natural route of a source at (X, ys, sn) to (X, yd).N0 and its code: the natural build (with dummy load)
    vs the same design with the dest input tied off, every route pinned by the natural .rcf."""
    d = f"{R}/work/cvn_{X}_{ys}_{yd}_{sn}"
    if os.path.exists(d + "/result.json"):
        return json.load(open(d + "/result.json"))
    os.makedirs(d, exist_ok=True)
    nat = d + "/nat"
    design2(nat, ys, yd, sn, True)
    res = {"ys": ys, "yd": yd, "sn": sn, "chain": None, "code": None}
    if subprocess.run([R + "/tools/qcompile.sh", nat], capture_output=True).returncode:
        json.dump(res, open(d + "/result.json", "w")); return res
    subprocess.run([Q + "/quartus_cdb", "top", "--back_annotate=routing"], cwd=nat, capture_output=True)
    rcf = open(nat + "/top.rcf").read()
    blk = re.search(r"signal_name = rs \{.*?\n\}", rcf, re.S).group(0)
    brs = rs_branches(rcf)
    wbr = [b for b in brs if "( w," in b]
    dummy = [b for b in brs if "( u," in b]
    if len(wbr) != 1 or len(dummy) != 1 or any(k in wbr[0] + dummy[0] for k in ("label", "branch_point")):
        json.dump(res, open(d + "/result.json", "w")); return res
    els = re.findall(r"(\w+):X(\d+)Y(\d+)S0I(\d+);", wbr[0])
    res["chain"] = [[t, int(x) - X, int(y) - yd, int(i)] for t, x, y, i in els]
    base = d + "/base"
    design2(base, ys, yd, sn, False)
    if subprocess.run([R + "/tools/qcompile.sh", base], capture_output=True).returncode:
        json.dump(res, open(d + "/result.json", "w")); return res
    open(base + "/top.rcf", "w").write(rcf.replace(blk, "signal_name = rs {\n" + dummy[0] + "\n}"))
    qsf = open(base + "/top.qsf").read()
    if "ROUTING_BACK_ANNOTATION_FILE" not in qsf:
        open(base + "/top.qsf", "a").write("set_global_assignment -name ROUTING_BACK_ANNOTATION_MODE NORMAL\nset_global_assignment -name ROUTING_BACK_ANNOTATION_FILE top.rcf\n")
    r = subprocess.run([Q + "/quartus_fit", "top"], cwd=base, capture_output=True, text=True)
    if "Error on line number" in r.stdout or r.returncode:
        json.dump(res, open(d + "/result.json", "w")); return res
    subprocess.run([Q + "/quartus_asm", "top"], cwd=base, capture_output=True)
    var, bb = open(nat + "/top.rbf", "rb").read(), open(base + "/top.rbf", "rb").read()
    hb, lane = RW[yd]; L0 = LIN(hb, lane)
    excl = elem_positions(X, yd)
    code = []
    for f in range(CB[X] - 30, CB[X] + 45):
        o = F0 + FLEN * f
        for byte in range(1, 296):
            on = (var[o + byte] & ~bb[o + byte]) & 0xFF
            for bit in range(8):
                if on >> bit & 1 and (f, byte, bit) not in excl:
                    code.append([f - CB[X], LIN(byte, bit) - L0])
    res["code"] = sorted(code)
    json.dump(res, open(d + "/result.json", "w"))
    for sub in ("nat", "base"):
        for s_ in ("db", "incremental_db"):
            shutil.rmtree(f"{d}/{sub}/{s_}", ignore_errors=True)
    return res


if __name__ == "__main__" and MODE == "natiso":
    DROWS = [int(v) for v in os.environ.get("DROWS", "29,30,31,32").split(",")]
    jobs = [(yd + dy, yd, sn) for yd in DROWS for dy in (-2, -1, 1, 2) if (X, yd + dy) in LEG for sn in range(0, 32, 2)]
    print("designs", len(jobs), flush=True)
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "2"))) as ex:
        for r in ex.map(lambda j: nat_iso(*j), jobs):
            print(r["ys"], r["yd"], r["sn"], r["chain"], None if r["code"] is None else len(r["code"]), flush=True)
    sys.exit(0)

if __name__ == "__main__":
    J = int(os.environ.get("J", "1"))
    if MODE == "record":
        jobs = []
        for yd in [y for y in ROWS if 26 <= y <= 33]:
            for dy in (-4, -3, -2, -1, 1, 2, 3, 4):
                ys = yd + dy
                if (X, ys) in LEG:
                    for sn in (2, 30):
                        jobs.append((ys, yd, sn))
        with cf.ThreadPoolExecutor(J) as ex:
            for (ys, yd, sn), rt in zip(jobs, ex.map(lambda j: natural(*j), jobs)):
                if rt:
                    print(ys, yd, sn, [rel(n, X, yd) for n in rt], flush=True)
    else:
        chains = collections.defaultdict(set)              # relative chain -> rows (yd) seen
        for d in os.listdir(R + "/work"):
            m = re.match(rf"cv_{X}_(\d+)_(\d+)_(\d+)$", d)
            if m and os.path.exists(f"{R}/work/{d}/route.json"):
                yd = int(m[2])
                rt = [rel(n, X, yd) for n in json.load(open(f"{R}/work/{d}/route.json"))]
                if rt and rt[0][0] == "LE_BUFFER" and rt[-1][0] == "LOCAL_INTERCONNECT" and any(h[0] == "C4" for h in rt):
                    chains[json.dumps(rt)].add(yd)
        print("distinct vertical C4 chains:", len(chains))
        out = []
        MINSEEN = int(os.environ.get("MINSEEN", "4"))
        for ch, seen in sorted(chains.items(), key=lambda t: -len(t[1])):
            chain = json.loads(ch)
            if len(seen) < MINSEEN or len(seen) > int(os.environ.get("MAXSEEN", "99")):
                continue
            if os.environ.get("DYS") and chain[0][2] not in {int(v) for v in os.environ["DYS"].split(",")}:
                continue
            # chains Quartus uses at every row phase: force at rows of different phases; phase-free if identical
            for phase in ([None] if len({y % 4 for y in seen}) == 4 else sorted({y % 4 for y in seen})):
                if os.environ.get("ALLROWS") and phase is not None:
                    rows = [y for y in ROWS if y % 4 == phase and (X, y + chain[0][2]) in LEG and 3 <= y <= 33][:int(os.environ.get("NROWS", "4"))]
                else:
                    rows = [y for y in sorted(seen) if (phase is None or y % 4 == phase) and (X, y + chain[0][2]) in LEG]
                if len(rows) < 4:
                    continue
                rnd = random.Random(hash(ch) & 0xFFFF); rnd.shuffle(rows)
                train, test = rows[:3], rows[3]
                alts = [json.loads(c2) for c2 in chains if c2 != ch and json.loads(c2)[0] == chain[0]]
                alts += [json.loads(c2) for c2 in chains if c2 != ch and json.loads(c2)[0][2] == chain[0][2] and json.loads(c2)[0] != chain[0]]

                with cf.ThreadPoolExecutor(J) as ex:
                    codes = list(ex.map(lambda y: forced_iso(chain, y), train + [test]))
                tr = [set(map(tuple, c)) for c in codes[:3] if c is not None]
                if len(tr) < 3 or len({frozenset(t) for t in tr}) != 1:
                    print("inconsistent/illegal", chain, phase, [None if c is None else len(c) for c in codes]); continue
                ok = codes[3] is not None and set(map(tuple, codes[3])) == tr[0]
                out.append({"chain": chain, "phase": phase, "x": X, "bits": sorted(tr[0]), "rows_train": train,
                            "row_test": test, "test_ok": ok})
                print("chain", chain, "phase", phase, "bits", len(tr[0]), "held-out", "OK" if ok else "FAIL", flush=True)
        p_ = R + f"/fuzz/col_vert_{X}.json"
        prev = json.load(open(p_)) if os.path.exists(p_) else []
        keys = {(json.dumps(e["chain"]), e["phase"]) for e in out}
        out += [e for e in prev if (json.dumps(e["chain"]), e["phase"]) not in keys]
        json.dump(out, open(p_, "w"), indent=0)
        print("entries", len(out), "held-out OK", sum(e["test_ok"] for e in out))
