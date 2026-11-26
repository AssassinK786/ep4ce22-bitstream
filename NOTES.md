# Cyclone IV E (EP4CE22F17C6) bitstream notes

Clean-room: derived only from Quartus II 13.1 compiler output (fuzzing). Tools in `tools/`.

## Container (.rbf, uncompressed, 718569 bytes) — DONE, see tools/rbf.py
- [0:32) FF, [32]=0x6A sync, [33:73) option header (holds JTAG USERCODE), [73:75) CRC-16 LE.
- [330:7482) periphery block: 1788 bytes, each byte sent 4x (meaning TBD: I/O, PLL, clocks?).
- [7482:) 2386 frames x 298 B: byte0=0x00, bytes 1..295 data, 296..297 CRC-16 LE over 1..295.
- CRC-16: poly 0x8005 reflected (0xA001), init 0xFFFF (MODBUS). Tail 59 x FF.
- Fix USERCODE (`USE_CHECKSUM_AS_USERCODE OFF`) or the header changes with every design.
- Verified: fix_crcs() is identity on Quartus output; patched base == Quartus variant byte-exact.

## LUT bits (logic element combinational part)
- One LAB column = 8 consecutive frames for LUT bits (X20: frames 708..715).
- Column frame pitch 35 between logic columns (X19: 673.., X20: 708.., X21: 743..);
  X22 is not logic (LCCOMB placement fails); X23 starts at 1071 (memory/DSP column in between).
- Inside a frame, a LAB row occupies ~70 bytes at one bit lane:
  Y10 -> bytes 68..133 bit 5, Y11 -> ~203 bit5, Y12 -> ~273 bit5, Y9 -> ~63 bit5,
  Y13 -> ~49 bit4, Y20 -> ~245 bit3, Y1 -> ~91 bit7  (rows packed across bytes and bit lanes).
- 16 LEs per LAB in byte pairs, N0 highest bytes (133/132), then N2 (131/130), N4 (125/124) ...
  Gaps between pairs (e.g. 126..129, 110..113, 96..105) are LAB-level and FF bits (to fuzz).
- Each LUT = 16 bits over 8 frames x 2 bytes. Stored bit = mask bit (no inversion).
- The mask-bit -> slot assignment changes with location because the fitter permutes LUT
  inputs to suit routing. The physical truth-table order needs input-pin knowledge (routing fuzz).

## Next
- FF / LAB-control bits; complete row->(byte,bit) map for Y1..Y30; all logic columns.
- Fix LUT input permutation (read back fitter pin assignment: quartus_cdb / chip planner tcl).
- Periphery 4x block; header option bits.

## LAB grid (fuzz/lab_grid.json, tools/gridmap.py) — DONE for LUT N0
- Die has 1539 LAB sites (37+11 logic columns X1..X52, rows Y1..Y33, some columns 28 rows).
  Quartus accepts each site but caps EP4CE22 at 1395 LABs total ("device contains only 1395 LABs").
  All 1539 sites have distinct, regular LUT bits (two half-grid compiles, 24624 bits, 0 exceptions).
- Column frame base: 35 frames per LAB column; +25 at X13/X42, +293 at X22/X33 (M9K/mult columns),
  +4 at X16/X38 (clock spine?). Row -> (high byte, bit lane): 4-5 rows per lane, pitch 70 bytes.
- LUT slot table (physical index k after fitter input permutation, from .vo):
  frame = colbase + 7 - k//2 ; byte = hibyte - s[k] with s = 0,1,1,0 repeating per k%4; odd LE pairs mirror.

## FF (fuzz/ff.json, X20_Y10 N1) — first pass
- FF use / ena / aclr / sclr bits sit in frames 700..707 and 716..719 (around the 8 LUT frames),
  bytes 99..103 (LAB control region) and 132..135 (per-LE).
- Clock inversion = single bit (709,103,5). power_up=high not placeable as written (retry).

## FF + LAB control (fuzz/ff_db.json, tools/fuzz_ff2.py) — DONE first pass
Coordinates relative to the LAB: (frame - colbase, row hibyte - byte, bit - row lane).
Verified identical at X20Y10, X5Y20, X45Y3 for N0/N14/N30.
- LAB-wide: clock invert (1,30,0); clock enable used (-1,30,0)+(0,30,0); aclr used (6,32,0);
  sclr used (-4,32,0)+(9,32,0); FF clock on (-12,32,0)+(-11,32,0)+(1,30,0).
  (Frames -12..-1 = columns' frames before the LUT block; 8..11 = after it.)
- Per LE (frames +8..+11): ff_used (8,a)+(11,b), aclr (10,b), sclr (11,a'); offsets per slot in ff_db.json.
- Remaining diff bits are routing (to be decoded in the routing phase).

## Routing — enabler found
`quartus_sta -t tools/routes.tcl` (report_path -show_routing) lists every routing element of a path
with its delay, e.g. IOIBUF -> CLK_BUFFER -> GEN_CORE_BUF -> R24_X45_Y17 (H_SEG24) -> C4_X20_Y13 (V_SEG4)
-> LOCAL_INTERCONNECT_X20_Y10_N0_I13 (LAB_LINE) -> LCCOMB datad -> LE_BUFFER -> C4/R4/R24 ->
BLOCK_INPUT_MUX (LEIM) -> IOOBUF. Gives wire names (graph) and per-hop delays (timing model).
Plan: per design, pair consecutive wires (pips) with diff bits; solve bit<->pip by intersecting
many random-routed designs (Project X-Ray style). Grid: I/O at X53 / Y34 edges.

## Routing, batch 1 (2026-11-25) — tools/route_fuzz.py, route_solve.py, route_holdout.py
200 specimens: 40 random LUT+FF cells pinned in LABs X19..21 x Y9..11, random 4-input wiring;
quartus_sta report_timing -show_routing gives ~650 wire hops per specimen (16402 distinct tags).
14003 CRAM bits vary. Pass 1 (bit pattern == one tag): 2565 unique + 2119 ambiguous.
Pass 2 (bit == OR of tags, shared mux bits): the remaining 9319, but large covers over-fit.
Hold-out (solve on 150, predict 50): single-tag bits 99.4 %, 2-4-tag covers 97-98 %,
9+-tag covers 80 % -> those are not real yet.
Unique matches by kind: LE_BUFFER->R4 356, LOCAL_INTERCONNECT->datad 319, R4->LI 299, C4->LI 253,
LE_BUFFER->C4 221, LE_BUFFER->LI 220, LI->datac 216, C4<->R4 ~180 each, LI->datab 146, LI->dataa 65,
FF->datac 54 (LE feedback), clock spine/LAB clock buffers.
Next: pool specimens in LAB-relative coordinates (same mux structure in every LAB), more specimens
and other regions; decode mux encodings (shared bits = mux select codes) instead of OR covers.

## LAB-relative mux decode (2026-11-26) — tools/mux_decode.py (MODE=lim|li), lim_decode.py, lim_holdout.py, rlabel.py
- Row byte wrap (needed for rows whose LAB runs past the frame start, e.g. Y9): a row runs downward from its
  high byte through frame bytes 295..2 and continues on lane+1 at byte 295 (period 294, bytes 2..295).
  rlabel.relbyte(); the earlier window without wrap left N28/N30 undecoded.
- LUT-input muxes (fuzz/lim_codes.json, 200 specimens, majority rule: sources with >=3 samples, >=90 % agreement):
  64/64 muxes decoded; bits per mux dataa 10, datab 12, datac 11, datad 12 (N12.datac 19 = 8 spurious).
  Every source has a distinct code. Hold-out (decode on 150, test 50): 7423/7437 = 99.81 % exact;
  97 samples from sources never seen in training (mostly LOCAL_LINE_I*_N0 feedback).
  Code tables are identical in all 16 LE slots for dataa/datab/datad (378/378, 454/454, 320/320) and
  284/303 for datac (misses from N12's extra bits). Frames: dataa -12,-11,-5..-3; datab -10..-6,-2;
  datac -12..-9,-3,-1; datad -8..-4,-2. Slot pitch 4 bytes, +8 extra between N14 and N16.
- Local-line drivers (MODE=li, fuzz/li_codes.json): NOT decoded. 38 lines (I0..I37), 8-23 sources each
  (C4 196, R4 187, LE_BUFFER 54, BLK_CLK_LIM 5 source labels). Per-source bit consistency fails in windows
  up to frames -45..45, bytes -80..150 and all 8 lanes: 0-4 bits per line at 90 % agreement; 80-96 % hold-out
  at looser thresholds with colliding codes. Separating bits sit in the column-edge frames (-17..-13, +18) at
  72-81 % agreement, and the bits that are always set for a C4 source are wire-usage bits at the wire's
  driver (same set for C4..._I19 into I30 or I1). Likely a two-level mux with a first stage shared between
  lines (or between the two LABs of a routing channel); needs a joint model, not per-line consistency.

## DE0-Nano blinky from our tools (2026-11-26) — tools/blinky_design.py, tools/blinky_gen.py
Design: 26-bit synchronous counter with no carry chain (LUT4 + FF per bit, an enable LUT every
3 bits; 34 LEs in LABs X38 Y31..33), clock 50 MHz on R8, q[25] -> LED0 (A15), ~1.34 s period.
Baseline work/bl_empty (M1 -> L3 only). Baseline vs Quartus build of the blinky: 529 CRAM bits
in 47 frames + 30 periphery bytes (x4).
Model check against the Quartus build:
- LUT contents (slot table + column/row model + .vo physical masks): 528 / 528 bits correct.
- LUT-input muxes (lim_codes.json + STA sources): 956 / 964 correct; 20 inputs fed from
  LOCAL_LINE (LE feedback) have no code yet.
- ff_db "ff_used": per-LE (8,a) never flips here and (11,b) flips in 17 / 26 LEs -> these are
  LE output-select bits (registered/comb to LE_BUFFER / LOCAL_LINE), not "FF used".
  LAB "ff_clock_on" matches in 2 of 3 LABs -> it encodes the LAB clock-line choice.
Residual copied as measured from the Quartus build: 199 CRAM bits (153 not modelled: global
clock spine/row buffers, LAB clock select, LE_BUFFER -> C4 -> IO-block LAB line -> LEIM ->
IOOBUF A15, LE feedback lines, clearing the baseline's M1 -> L3 path; 46 where the FF model
above is wrong), and the 120 periphery bytes (IOB standard/enable for A15 and R8).
Output work/blinky_ours.rbf: byte-identical to Quartus (by construction for the residual).
Load: openFPGALoader -c usb-blaster work/blinky_ours.rbf (SRAM).
Open for a model-only blinky: global clock chain bits, output-path bits (LE output select,
LE_BUFFER -> C4, IO LAB line -> LEIM -> IOOBUF), IOB periphery bytes, LOCAL_LINE codes.

## DE0-Nano blinky generator v2 (2026-11-26) — tools/blinky_gen.py (v1: blinky_gen_v1.py)
Baseline is now an "empty device": bitwise majority of three trivial pin-to-pin designs
(work/bl_e1..e3, disjoint pins/paths). Output stays byte-identical to Quartus (residual copied).

| group | source | checked vs Quartus |
|---|---|---|
| LUT contents | lut_slots + lab_grid | 544/544 |
| LUT-input muxes | lim_codes_ll.json (+128 LOCAL_LINE feedback codes, tools/lim_ll.py; slot fallback per port) | 1184/1184 (82 via slot fallback); 0 inputs without code |
| LE local-output driver select | lab_solve.py on 64 work/lb_* specimens: frame +9, byte LEOFF+1 (even pair member) / +0 (odd); 1 = comb, 0 = reg | 28/28 |
| Pin I/O (8 LEDs out, KEY0/1 + 4 DIP in) | fuzz_pins.py + pin_solve.py: per pin 0-3 CRAM bits + 5-14 periphery bytes (fuzz/pins.json) | A15 used: ok |
| A15 output path from (38,31) N3 | fuzz_vote.py three-design vote (A15 vs A13 vs B13): 14 bits + 12 periph bytes (fuzz/paths.json) | 14/14 |
| R8 clock tree to LABs (38,31..33) | fuzz_vote.py vote (R8 vs E1 vs J15 as clock): 10 bits + 3 periph bytes (fuzz/clock_tree.json) | 8/10 |
| Clock chain common to 12 LABs | fuzz_clk.py + clk_solve.py: 7 chain bits + 1 LAB-relative bit (fuzz/clock.json) | 10/10 |

Copied as measured: 199 CRAM bits + 30 periphery bytes (v1) -> 107 CRAM bits + 4 periphery bytes (v2).
Left: ~79 bits inside the three LABs (per-LE FF/LE-buffer bits at frames -1, 8, 11, 13/14 next to each
LE's byte offset; LAB-level (-12,32) (-11,32) (1,30) (-8,30) (-2,31) (-13,4) (-13,20); inter-LAB
routing LE_BUFFER -> R4/C4 -> LOCAL_INTERCONNECT drivers), ~26 outside (rest of the clock spine
and row enables), 2 wrong clock-tree bits, 4 periphery bytes.
Notes: the old ff_db.json "ff_used" (8,a) bits are not FF-used bits; STA reports list only some
paths, so labels derived from them (LE-buffer select, FF used) are too incomplete to decode those
bits — they need labels by construction (vote designs), like the path and clock tables.
Per-LE / per-LAB "clock region" tables from ck/nc pairs were wrong (62/76): ck and nc also differ
in routing; the vote method replaced them.

## DE0-Nano blinky, round 3 (2026-11-26): two-LAB layout, votes
- n flops give at most 2^n states; a visible blink at 50 MHz needs ~24 bits, so one LAB (16 LEs) cannot
  blink visibly. New layout tools/blinky2_design.py (work/bl2_full): 24-bit counter, LAB A (38,32) bits
  0..11 + enables, LAB B (38,31) bits 12..23, bit 23 FF at (38,31) N3 -> A15 (decoded path). Only one net
  (t4) crosses, on a direct link (LE_BUFFER_X38_Y32_I30 -> LOCAL_INTERCONNECT_X38_Y31_I15). LED toggles ~0.17 s.
- New decoded rules: per-LE register-used bit (11, b) = 1 at the old ff_db "(11, b)" positions
  (fuzz_vote2.py, common to 3 LABs; 20/22 right on bl2); the old (8, a) "ff_used" bits were wrong.
  R8 clock tree for LABs (38,31)+(38,32) by vote (R8 vs E1 vs J15): 8 bits + 3 periph bytes, 8/8.
- Generator: DESIGN=bl2_full TREE=clock_tree2.json python3 tools/blinky_gen.py
  -> work/bl2_full_ours.rbf (byte-identical, residual copied), work/bl2_full_model_only.rbf.
- Still copied for bl2: 72 CRAM bits + 4 periphery bytes:
  * local-line (LAB input) mux drivers: Quartus routes 12 intra-LAB nets through LE_BUFFER -> own LAB
    LOCAL_INTERCONNECT, plus the t4 direct link. Per-(line, source) majority codes from 650+ specimens are
    mostly right (8 of 13 hops exact) but not exact; the direct-link code was wrong (9/10 bits). The LAB
    line mux shares select bits between lines (per-line consistency fails); the pairing is not identified
    (a "partner line" search was dominated by rare-line artefacts).
  * per-LE frame -1 bit pairs (one per LE: (-1, 1/2), (-1, 9/10), ...), frame 8 and 13/14 bits — likely
    LE_BUFFER drive / LAB-line driver side; the FF vote did not isolate them (X/Y chains also route differently).
  * LAB-level (-12,32) (-11,32) (1,30) (-8,30) (-2,31) (-13,x): LAB clock line select / LAB control.
  * 17 bits outside the LABs in frames 1837..1843 (left neighbour column: LAB-line / clock spine side).
  * 4 periphery bytes (logical 296/297/594/595 region: global I/O or clock settings).
- Next: decode the LAB-line mux jointly (pairs of lines, source per line) with targeted specimens that fix
  one line's source and vary its partner; then the frame -1/8/13/14 driver bits fall out of the same data.

## Local-line round (2026-11-26)
- tools/li_joint.py: joint decode of LAB local-line (LOCAL_INTERCONNECT I0..I37) driver bits, LAB-relative,
  window frames -25..25 (the left column's frames -21..-15 hold line-driver bits too). Per bit: the line (or
  line pair) whose sources determine it, with a real-dependence test (table takes both values; beats the
  bit's majority rate by >= 80 % of its error). 145 bits explained; holdout (train 230 specimens, test the
  rest): 46184 right, 241 wrong, 120 unseen source combos -> 99.48 %. Structure: lines I0..I14 -> frames
  13..15 (bytes stepping with the line index), I15..I29 -> left-column frames, I30..I37 -> frames -14/-13,
  I7/I8 also -9..-2 and 11/12. Almost every bit depends on ONE line's source; pairs are rare.
- tools/feat_solve.py: (-1, x) per LE = "LE used" (any output used), not "FF present" (comb-only LEs that
  drive outputs set it too); BLK_CLK_LIM_I5 used -> (11,35), (-18,35); BLK_CLK_BUF_I0 -> (18,30), (-17,30).
- tools/fuzz_vote3.py (comb -> LE_BUFFER vote at 3 LABs): LE n owns LE_BUFFER I<n> and I<n+1>; combout ->
  buffer I<m> sets (8, LEOFF[n] + m - n). (11, b) is ~90 % "FF present", ~96 % "FF drives the LE_BUFFER";
  neither is exact.
- Periphery block = 6 logical frames x 298 bytes with the CRAM frame layout and CRC-16 (logical bytes
  296/297, 594/595, ... are CRCs). rbf.fix_crcs()/check() now cover them; verified on all 1124 Quartus
  bitstreams (0 failures; fix_crcs is the identity on Quartus output).
- bl2_full model-only (work/bl2_full_model_only.rbf): periphery identical; 24 CRAM bits differ from Quartus:
  LAB 31: (-12,32) (-11,32) (1,30) (-13,45) (8,16) (8,17) (11,6) (11,13) (13,13) (14,12);
  LAB 32: (-13,4) (13,13) (13,21) (13,44) (14,12); 9 in the left column (frames 1837..1843);
  i.e. local-line bits whose source combination was never seen in training, the LAB-31 bits tied to the
  clock entering as data (BLK_CLK_LIM_I5 -> line I8), the (11, b) rule (2 LEs), one (8, .) buffer bit.
