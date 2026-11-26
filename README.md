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
| Local-line drivers (LE buffer / R4 / C4 / neighbour -> local line) | structural 2-bit codes per (line, source), read by forcing routes through Quartus `.rcf` files at 3 LABs (60 codes, identical across LABs); statistical model for the rest |
| FF / LE output select, LE used, comb -> LE buffer | decoded (votes at 3+ LABs) |
| Clock chain pin R8 -> global -> LAB clock | decoded for the LABs used by the blinky |
| Pins | settings for every DE0-Nano user pin (8 LEDs, 2 keys, 4 switches, clock) |
| Periphery block | 6 frames x 298 bytes with frame CRCs, same layout as CRAM; written and checked by `rbf.py` |
| DE0-Nano blinky from our own tools | **done**: `examples/de0nano_blinky_model_only.rbf` is built from decoded models only (every CRAM and periphery bit), byte-identical to Quartus's build of the same placed design, and runs on the board (24-bit counter, LED0 on A15). Placement and routing choices still come from Quartus reports. A second layout using R4/C4 entries is 5 bits short. |
| Open place and route (`tools/pnr/`) | **runs on the board**: Verilog -> Yosys -> our packing, annealing placement and routing -> decoded bit models -> `.rbf`, with no Quartus anywhere. `examples/de0nano_cnt24_openflow.rbf` (from `examples/de0nano_cnt24_openflow.v`, a 24-bit counter on LED0) blinks on a DE0-Nano. Inputs and outputs work too: `examples/de0nano_sw_led_openflow.*` (KEY0 -> LED0, DIP SW0-3 -> LED1-4) and `examples/de0nano_key_toggle_openflow.*` (each KEY0 press toggles LED0) run on the board; a 24-bit LFSR runs (LED0 at 50 % duty, measured from video). Limits: logic in 3 LABs next to the pins, fixed pin slots in LAB (38,30), clock from R8, vertical links only between LABs (general R4/C4 routing in progress), flops power up at 0, +1 cycle on inputs. |
| M9K, multipliers, PLL | not started |

Details are in [NOTES.md](NOTES.md). JTAG reports IDCODE 0x020F30DD, shared by the EP3C25, EP4CE22 and 10CL025 (likely one die).

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
DESIGN=bl2_full python3 tools/blinky_gen.py   # model-only blinky; openFPGALoader -c usb-blaster <rbf>
python3 tools/pnr/pnr.py design.v NAME [--pins NAME.pins]   # open flow: Verilog -> work/pnr_NAME_*.rbf
```

Builds go to `work/` (not tracked). Results are written to `fuzz/*.json`.

## Licence

Code: Apache-2.0 ([LICENSE](LICENSE)). Data in `fuzz/` and the notes: CC-BY-4.0 ([LICENSE-DATA](LICENSE-DATA)).
