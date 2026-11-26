# ep4ce22-bitstream: Cyclone IV E EP4CE22 bitstream mapping

Black-box mapping of the configuration bitstream of the Intel/Altera Cyclone IV E
**EP4CE22F17C6** (Terasic DE0-Nano), towards an open place-and-route flow.

The method is clean-room: compile small designs with Quartus, diff the uncompressed `.rbf`
files, and use Quartus's ordinary text outputs (fitter reports, post-fit `.vo` netlists,
timing reports). Nothing here reads Quartus binaries or its internal databases.

Related work: [14sea/Cyclone_CRAM_Mapper](https://github.com/14sea/Cyclone_CRAM_Mapper)
(EP4CE6 die) and [kalj/c10lp](https://github.com/kalj/c10lp) (10CL016 / EP4CE15 die).
The EP4CE22 is a different die, so the constants here are new; no code is shared with those projects.

## Status

| Area | State |
|---|---|
| Container: header, CRC-16, 2386 × 298-byte frames | done; re-encoding is byte-identical to Quartus |
| LUT bits, all LAB sites | done; 1539 sites (Quartus caps the EP4CE22 at 1395 LABs) |
| LUT input order (fitter permutation) | done, via post-fit `.vo` |
| FF and LAB control bits | first pass, consistent across three LABs |
| LUT-input muxes (local line -> LUT input) | done; one code table per port for all 16 LEs, 99.8 % on held-out specimens |
| Routing between LABs (R4/C4/R24/C16 -> local lines) | in progress; random and single-net specimens, wire names and delays from `report_timing -show_routing` |
| Clock path pin -> global -> LAB clock | in progress (single-net specimens) |
| I/O, M9K, multipliers, PLL | not started |

Details are in [NOTES.md](NOTES.md).

## Requirements

- Quartus II 13.1 (Web Edition) with Cyclone IV device support. Set `QUARTUS_BIN` if it is not
  at `~/altera/13.1/quartus/bin`.
- Python 3.

## Usage

```bash
tools/qcompile.sh <dir>               # compile <dir>/top.v (+ extra.qsf) -> top.rbf (~15 s)
python3 tools/rbf.py file.rbf         # check header CRC, frame CRCs, periphery block
J=4 python3 tools/fuzz_le.py          # LUT geometry over LE slots, columns and rows
HALF=L python3 tools/gridmap.py       # map every LAB site (run with HALF=L and HALF=R)
J=3 python3 tools/fuzz_ff2.py         # FF / LAB-control bits
python3 tools/test_roundtrip.py       # patch LUT bits + re-CRC == Quartus output
J=3 N=200 python3 tools/route_fuzz.py # random routing specimens (work/rt_*)
python3 tools/route_solve.py          # bit <-> routing hop tags; route_holdout.py checks it
python3 tools/lim_decode.py           # LUT-input mux codes, LAB-relative; lim_holdout.py checks it
J=3 N=400 python3 tools/route_sparse.py && python3 tools/sparse_solve.py   # single-net specimens
```

Builds go to `work/` (not tracked). Results are written to `fuzz/*.json`.

## Licence

Code: Apache-2.0 ([LICENSE](LICENSE)). Data in `fuzz/` and the notes: CC-BY-4.0 ([LICENSE-DATA](LICENSE-DATA)).
