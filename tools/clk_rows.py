#!/usr/bin/env python3
"""Per-row clock tree of column X by vote (R8 vs E1 vs J15 as the clock), one FF at (X, y).
fuzz/clock_rows_<X>.json {y: [entries]}; `python3 tools/clk_rows.py tree X y1,y2,..` writes the union as
fuzz/clock_tree_<X>_<y1>_<y2>...json (the TREE file blinky_gen reads).
usage: python3 tools/clk_rows.py measure 38 26,27,...   |   python3 tools/clk_rows.py tree 38 28,29,30,31"""
import os, sys, json, subprocess, concurrent.futures as cf
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
from fuzz_vote import FF, vote
MODE, X, ROWS = sys.argv[1], int(sys.argv[2]), [int(v) for v in sys.argv[3].split(",")]
OUT = R + f"/fuzz/clock_rows_{X}.json"


def build(y, pin):
    tag = f"tree_r{X}_{y}_{pin}"; d = f"{R}/work/vt_{tag}"
    os.makedirs(d, exist_ok=True)
    open(d + "/top.v", "w").write("module top(input clk, input a, output y);\n  " + FF.format(n="r1", c="clk", d="a", q="y") + "\nendmodule\n")
    open(d + "/extra.qsf", "w").write(f"set_location_assignment PIN_{pin} -to clk\nset_location_assignment PIN_M1 -to a\n"
                                      f"set_location_assignment PIN_A15 -to y\nset_location_assignment FF_X{X}_Y{y}_N1 -to r1\n")
    if not os.path.exists(d + "/top.rbf"):
        subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True)
        subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
    return tag


if MODE == "set":
    pass
elif MODE == "measure":
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    jobs = [(y, p) for y in ROWS for p in ("R8", "E1", "J15")]
    with cf.ThreadPoolExecutor(int(os.environ.get("J", "1"))) as ex:
        list(ex.map(lambda j: build(*j), jobs))
    for y in ROWS:
        t = vote(f"tree_r{X}_{y}_R8", f"tree_r{X}_{y}_E1", f"tree_r{X}_{y}_J15")
        res[str(y)] = t
        print(y, "cram", sum(e[0] == "cram" for e in t), "periph", sum(e[0] == "periph" for e in t))
    json.dump(res, open(OUT, "w"), indent=0)
elif MODE == "tree":
    res = json.load(open(OUT))
    union = {}
    for y in ROWS:
        for e in res[str(y)]:
            union[json.dumps(e[:-1])] = e
    name = f"clock_tree_{X}_" + "_".join(map(str, ROWS)) + ".json"
    json.dump({"R8_rows": list(union.values())}, open(R + "/fuzz/" + name, "w"), indent=0)
    print(name, len(union), "entries")


def set_tree(rows_):
    """Clock tree of a LAB set (one FF per row, chained), by vote; writes fuzz/clock_tree_<X>_<rows>.json."""
    tags = []
    for pin in ("R8", "E1", "J15"):
        tag = f"tree_s{X}_" + "_".join(map(str, rows_)) + f"_{pin}"; d = f"{R}/work/vt_{tag}"
        os.makedirs(d, exist_ok=True)
        v = ["module top(input clk, input a, output y);"] + [f"  wire q{i};" for i in range(len(rows_))]
        q = [f"set_location_assignment PIN_{pin} -to clk", "set_location_assignment PIN_M1 -to a", "set_location_assignment PIN_A15 -to y"]
        prev = "a"
        for i, y in enumerate(rows_):
            v.append("  " + FF.format(n=f"r{i}", c="clk", d=prev, q=f"q{i}")); prev = f"q{i}"
            q.append(f"set_location_assignment FF_X{X}_Y{y}_N1 -to r{i}")
        v += [f"  assign y = {prev};", "endmodule"]
        open(d + "/top.v", "w").write("\n".join(v) + "\n"); open(d + "/extra.qsf", "w").write("\n".join(q) + "\n")
        if not os.path.exists(d + "/top.rbf"):
            subprocess.run([R + "/tools/qcompile.sh", d], capture_output=True)
            subprocess.run(["rm", "-rf", f"{d}/db", f"{d}/incremental_db", f"{d}/top.sof"])
        tags.append(tag)
    t = vote(*tags)
    name = f"clock_tree_{X}_" + "_".join(map(str, rows_)) + ".json"
    json.dump({"R8_set": t}, open(R + "/fuzz/" + name, "w"), indent=0)
    print(name, "cram", sum(e[0] == "cram" for e in t), "periph", sum(e[0] == "periph" for e in t))


if MODE == "set":
    set_tree(ROWS)
