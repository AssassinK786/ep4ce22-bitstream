#!/usr/bin/env python3
"""Local-line bits as an OR of (line, source) indicators (shared first-stage mux bits).

For every varying LAB-window bit that li_joint.py / known models do not explain:
  S_b = {(k, s): line k has source s in >= MINS training samples and bit = 1 in >= PIN of them}
  prediction = 1 if any (k, s) in S_b holds for the sample, else 0.
A bit is kept when the OR model reaches >= ACC on the training samples. Holdout as li_joint.py.
Output: fuzz/li_or.json {"df,db": [[k, src], ...]}
"""
import os, sys, json, collections
import numpy as np
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R + "/tools")
os.environ.setdefault("DFR", "-25,26")
SRC = open(R + "/tools/li_joint.py").read().replace(
    "R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))", f"R = {R!r}")
exec(SRC.split("var = ~(W[tr]")[0])
MINS, PIN, ACC = int(os.environ.get("MINS", "3")), float(os.environ.get("PIN", "0.9")), float(os.environ.get("ACC", "0.985"))
J = json.load(open(R + "/fuzz/li_joint.json"))
S = np.array(S_src)
TRI, TEI = np.nonzero(tr)[0], np.nonzero(~tr)[0]
var = ~(W[TRI] == W[TRI][0]).all(0)
pairs = collections.defaultdict(list)                  # (k, s) -> train sample indices
for i in TRI:
    for k in range(NL):
        if S[i, k] != "-":
            pairs[(k, S[i, k])].append(i)
pairs = {p: np.array(v) for p, v in pairs.items() if len(v) >= MINS}
ind = {p: (S[:, p[0]] == p[1]) for p in pairs}
out = {}
for i, j in np.argwhere(var):
    key = f"{DF[i]},{DB[j]}"
    if (DF[i], DB[j]) in known or key in J:
        continue
    col = W[:, i, j]
    Sb = [p for p, ix in pairs.items() if col[ix].mean() >= PIN]
    if not Sb:
        continue
    pred = np.zeros(len(col), bool)
    for p in Sb:
        pred |= ind[p]
    acc = (pred[TRI] == col[TRI].astype(bool)).mean()
    null = max(col[TRI].mean(), 1 - col[TRI].mean())
    if acc >= ACC and acc > null:
        out[key] = [list(p) for p in Sb]
print("OR-model bits", len(out))
if len(TEI):
    ok = bad = 0
    for key, Sb in out.items():
        df, db = map(int, key.split(","))
        col = W[TEI, list(DF).index(df), list(DB).index(db)].astype(bool)
        pred = np.zeros(len(TEI), bool)
        for k, s in Sb:
            pred |= S[TEI, k] == s
        ok += int((pred == col).sum()); bad += int((pred != col).sum())
    print(f"holdout: {ok} right, {bad} wrong -> {ok / max(1, ok + bad):.4f}")
json.dump(out, open(R + "/fuzz/li_or.json", "w"), indent=0)
