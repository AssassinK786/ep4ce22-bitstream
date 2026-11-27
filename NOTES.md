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

## Closing round (2026-11-26) — not yet byte-identical
- Training data: tools/fuzz_bv.py, the bl2 counter at 10 other LAB pairs (work/bv_*), added to
  li_joint.py / feat_solve.py / li_or.py.
- LAB clock via the control mux: LAB_CONTROL_MUX_I1 fed from local line I8 (BLK_CLK_BUF -> BLK_CLK_LIM ->
  I8 -> LAB_CONTROL_MUX_I1) sets (-12,32), (-11,32), (1,30) (feat_solve.py, now a feature).
- tools/li_or.py: line bits as an OR of (line, source) indicators (shared first stage). ACC 0.985:
  24 bits, holdout 99.27 %. Looser thresholds add bits but lose accuracy (0.95: 68 bits, 97.6 %).
- Row wrap fixed: rows use frame bytes 1..295 (295 per lane) before continuing on the next lane
  (rlabel.py; was 294 / from byte 2). Found with bl3 (row Y30 wraps): LUT 8 wrong -> 0, LIM 23 -> 0.
- Generalisation design bl3 (tools/blinky2_design.py bl3_full 38 30 38 31: LAB A below the LED LAB;
  clock tree by vote, fuzz/clock_tree3.json).
- Model-only vs Quartus (CRAM bits differ; periphery identical in both):
  bl2_full 25: left column 9 (line drivers of I15..I29), frame 8 LE-buffer select 5, frames 13-15
           (lines I0..I14) 5, frame 9 3, (11, b) 2, frames -14..-2 1.
  bl3_full 20: left column 11, frames -14..-2 2, frame 8 2, frames 13-15 2, frame 9 1, frames 19/21 2.
  Most are local-line bits whose value depends on more than one (line, source) pair, plus the LE-buffer
  select bits (frame 8) and the (11, b) rule.

## Structural round (2026-11-26) — routing constraints (.rcf)
- `quartus_cdb top --back_annotate=routing` writes top.rcf: the COMPLETE routing of every net
  (LOCAL_LINE / LE_BUFFER / R4 / C4 / LOCAL_INTERCONNECT hops, branch points, and the physical LUT input
  `route_port` for every destination). Re-fitting with ROUTING_BACK_ANNOTATION_FILE makes the fitter
  follow an edited .rcf; an illegal hop is reported ("Error on line number N in Routing Constraints
  File") and that fan-out is re-routed. Ordinary Quartus input/output -> clean-room controlled experiments.
  (STA reports only list nets on reported paths; the .rcf is the better label source.)
- tools/rcf_probe.py: move a LE_BUFFER -> LOCAL_INTERCONNECT hop to every other line and re-fit.
  Block (38,30) of bl3, 7 such hops: every move of LE_BUFFER I7 (line I31) and I15 (line I33) to any other
  line is illegal -> each own LE_BUFFER reaches exactly ONE local line of its LAB (fixed wiring:
  I1->I15, I3->I30, I7->I31, I12->I5, I15->I33, I20->I35, I22->I25 seen). So the (line, own LE_BUFFER)
  code is fixed per line; what varies is which of a line's legal sources (own LE_BUFFER, neighbour
  links, R4/C4) drives it. Next experiment: keep the line, change its source (move the driving net to a
  neighbour LAB / an R4 entry via the .rcf).
- (11, b) is not the clock source index (BLK_CLK_BUF_I*) nor "lowest register of each 4-LE group"
  (lowest: 556x0 / 4954x1, others: 442x0 / 2575x1) in this data.
- bl2_full / bl3_full model-only: unchanged this round (25 / 20 CRAM bits differ; periphery identical).

## .rcf source sweep (2026-11-26)
- tools/src_sweep.py: single-net designs (source FF at a chosen LE -> dest LUT L.N0 datab), complete routing
  from the .rcf, code = diff vs the same design with datab = 0. LAB (20,10): neighbour links are fixed
  wiring with a regular map: left LAB LE_BUFFER I0/2/4/8/10/12/... -> lines 15/16/17/18/19/20/...,
  I6 -> 31, I14 -> 33, I17 -> 34; right LAB LE_BUFFER I1/3/5/... -> lines 0/1/2/.../13.
  Every (line, source) sets a 2-bit code inside the line's own group: right-LAB sources (13, 4k) + (15, 4k);
  left-LAB sources (-19, b) + (-17, b') for lines 16..29, (-16, x) + (-14/-15, x') for 31/33/34;
  C4 sources frame 14 (+13); R4 sources frames -19/-17, -18 or -14. (Shared "first-stage" bits = the
  two halves of these 2-bit codes.)
- tools/force_probe.py: own-LAB and vertical hops forced with edited .rcf (label/branch_point) and re-fit;
  accepted pairs give codes, e.g. own I3 -> line 30: (-13,4); I5 -> 17: (-18,7)+(-17,7); I7 -> 31:
  (-16,11)+(-15,11); I12 -> 5: (13,21)+(14,20); I22 -> 25: (-18,50)+(-17,51); I27 -> 13: (13,60)+(14,61);
  I28 -> 29: (-18,66)+(-17,66); I30 -> 29: (-19,67)+(-17,67). Many pairs were rejected by the fitter
  (likely .rcf syntax when the pin branch shares the buffer, or the pair is not legal) — incl. the
  vertical links and own I1/I8/I11/I15/I19/I20 that bl2/bl3 use.
- tools/li_struct.py -> fuzz/li_struct.json: 46 (line, source) codes; 7 seen identical at >1 LAB, 1
  disagreeing (31|LE_BUFFER_I7 at (12,5): extra bits, probably a second net). Generator applies them (LI-S):
  bl2 8/8, bl3 8/8 right.
- Model-only vs Quartus: bl2_full 23 CRAM bits, bl3_full 19 (periphery identical). Left: OR-model local-line
  bits for the pairs whose code was not measured (bl2 6, bl3 2 wrong), the (11,b) rule (bl2 2), one frame-8
  buffer bit each, plus unmodelled bits of the vertical link and own I1/I8/I11/I15/I19/I20 lines.
- Next: fix the .rcf edit for the rejected pairs (avoid branch_point: give the pin its own source LE, so
  the forced net has a single branch), then sweep every own buffer and both vertical directions.

## Single-branch .rcf sweep (2026-11-26)
- tools/force2_probe.py: the source FF drives ONLY the dest LUT (single-branch net); its .rcf block is replaced
  by LE_BUFFER I<m> -> LOCAL_INTERCONNECT I<k> -> dest WITHOUT route_port (pinning the physical LUT input made
  most forced lines illegal: each line reaches only some LUT inputs). Diff vs the naturally routed design:
  bits that turn on = the forced pair's code; bits that turn off = the natural hop's code (also harvested).
  3 LABs ((20,10), (30,25), (12,5)): 20-22 of 88 candidate pairs legal per LAB (the rest: lines a buffer does
  not reach). Codes are 2-bit and LAB-relative, e.g. own I8->3 (13,13)+(14,12), I19->10 (13,44)+(14,45),
  I20->35 (-16,44)+(-13,45), I15->33 (-16,28)+(-15,28), I9->18 (-18,15)+(-17,14), I4->1 (13,4)+(14,4).
  Line 15 is the default selection: own I1, own I3, vertical (above) I30 -> 15 all have an all-zero code.
- fuzz/li_struct.json: 60 (line, source) codes, 22 seen identical at >1 LAB, 0 disagreeing (the old
  multi-branch force_*.json results are no longer used).
- Generator: structural codes win; the statistical joint/OR tables are skipped for lines with a structural
  code and never write element-plane frames (-1, 8, 9, 11) — that was where 6 of the OR errors came from.
  New rule: LAB with clocked FFs -> (-21, 64) = 0 (1 in every empty design; 0 in 1096/1147 clocked LABs).
- Model-only vs Quartus (periphery identical):
  bl2_full 9:  LAB 32 (-19,68) (-17,68) (-17,35); frames 1840/1841 byte 203 (outside the LAB windows);
               LAB 31 (8,17) unmodelled + (8,16) C2BUF wrong (LE-buffer select of the LED FF N2/N3);
               LAB 31 (11,13) (11,6) (11,b) rule wrong.
  bl3_full 11: LAB 30 (-18,12) (-17,12) (-17,35), LAB 31 (-18,68) (-17,68) (-18,35) (14,12), (8,16)/(8,17),
               LAB 30 (19,65) (21,65).
  The row-byte 68 bits sit just outside the 0..69 window the probes measured (the neighbouring row's
  share of a line group); frame 8/11 are the register-side LE-buffer select and the (11, b) bit.

## bl2_full model-only = Quartus, byte for byte (2026-11-26)
work/bl2_full_model_only.rbf is byte-identical to Quartus's bl2_full build (sha256 95c091a230fd55b4...),
built from decoded models only: the generator reads Quartus's report files for the design (placement, post-fit
LUT masks, routing hops) but never its bitstream (that is used only to score the model). Last steps:
- tools/force2_wide.py: force2 codes re-derived with a wide window (row bytes -12..82). Line 15 codes live in
  the previous row's bytes: own I1 -> 15 = (-18,-2)+(-17,-2); own I3 -> 15 = (-18,-1)+(-17,-1);
  vertical (LAB above) I30 -> 15 = (-19,-2)+(-17,-2) (tools/tied_probe.py, common to 3 LABs).
- Register driving its LE_BUFFER needs no select change (force2 src_bits empty) -> frame 8 = 0 for registers.
  Comb -> LE_BUFFER I<m> of LE n sets (8, LEOFF[n] + off), off = m-n for odd pair members and 1-(m-n) for
  even ones (mirrored like the LUT slots).
- (11, b) = clock-pair select: 0 when the FF is clocked straight from BLK_CLK_BUF in a LAB where some FF uses
  the LAB_CONTROL_MUX clock, else 1 (training data ~97 %; exact on bl2/bl3).
- LAB clock line i: direct FF clocking from BLK_CLK_BUF_I<i> sets (-17, 30+i) without, (-18, 30+i) with the
  clock also entering a local line (BLK_CLK_LIM_I<i>); neither if no FF is clocked directly.
- LAB with clocked FFs: (-21, 64) = 0.
bl3_full model-only: 5 CRAM bits left, all tied to its R4 / C4 entries (line 2 <- R4 I16 in LAB 30,
line 3 <- C4 I11 in LAB 31) and their wire drivers: LAB 30 (-18,12) (-17,12), LAB 31 (14,12),
LAB 30 (19,65) (21,65). Next: force2 with R4/C4 sources to get those codes.

## Open P&R prototype (tools/pnr/, 2026-11-26)
Verilog -> bitstream with no Quartus in the flow:
- `pnr.py`: Yosys generic synth (`synth -flatten; abc -lut 4`) -> pack (DFF joins the LUT on its D,
  else a route-through LUT) -> annealing placement over a vertical LAB stack -> per-LAB router
  (backtracking over LUT-input port permutations) -> design directory in the format
  `tools/blinky_gen.py` reads (extra.qsf placement, LUT masks as .vo defparams, hops as pips.json).
  The decoded bit models then write the RBF (`DESIGN=<name> TREE=clock_tree_pnr.json blinky_gen.py`;
  use the `*_model_only.rbf`; its "score" is against an empty-device placeholder and means nothing).
- Router hop types, each used only when both codes are decoded: own FF -> datac (FF_N{n+1}), LE local
  line (LOCAL_LINE_I{n/2}), own LE buffer I{n}/I{n+1} -> local interconnect line (li_struct.json),
  vertical neighbour buffer (down: LE N30 buffer I30 -> line 15; up: LE N0 buffer I1 -> line 29),
  then the line's LUT-input code (lim_codes_ll.json). Unused LUT ports are made don't-care in the mask.
- Fixed by what is decoded: LED0 only, from the FF of LE N2 in LAB (38,31) (fuzz/paths.json); clock
  from R8, every FF on BLK_CLK_BUF_I5; LABs (38,30..32) (`fuzz/clock_tree_pnr.json` = union of the
  two measured trees, no conflicts on their 9 shared entries).
- `simcheck.py`: cycle simulation of the emitted LE netlist (masks + routed ports, read back from the
  design directory) against the counter. `qcheck.py`: compiles the same LE netlist in Quartus with our
  placement as location assignments and compares every LUT function.

Results:
- cnt24 (24-bit counter, LED0 = c[23]): 31 LUTs/24 DFFs -> 31 LEs in 3 LABs, 156 hops, every LUT input
  has a code, 0 model conflicts -> work/pnr_cnt24_model_only.rbf (container checks OK).
  simcheck: 5000 cycles, 0 mismatches (97 routed inputs). qcheck: Quartus accepts the placement, LUT
  functions equal 31/31.
- Model generality check: same placement, Quartus routing, bit models vs Quartus's bitstream: 7 bits differ
  (2 CLOCK: clock.json "lab" entry (11,-2) lands in the row above, likely the (11,b) register bit of the
  LAB above, right for bl2's layout only; 5 unmodelled bits at frames 1840/1841/1845, column-edge frames).
  So pnr_cnt24_model_only.rbf may carry the same 2 CLOCK-bit errors; not board-tested (not loaded).
- Limits: one decoded link per direction between stacked LABs, tied to LE N30 (down) / N0 (up), so
  designs with more cross-LAB nets often don't place (burst.v: best cost one violation).
  Next: inter-LAB R4/C4 codes (tools/routing_model.py), input pins, the other LED paths, clock trees
  for any LAB, LAB-wide control signals (ena/clr), carry chains.

## Inter-LAB wires and the routing_model API (2026-11-26)
- tools/force3_probe.py: force any LAB-relative chain [(LE_BUFFER, dx, dy, m), (R4|C4|R24|C16, dx, dy, i), ...,
  (LOCAL_INTERCONNECT, 0, 0, k)] with an edited .rcf; bits that turn on = the chain's code (wide window).
  Findings: wires are fixed-wired into lines like LE buffers (C4 I11 at (x, y) reaches ONLY local line 3 of
  that LAB; all 14 other lines rejected); legality of an R4 index depends on the column (R4 I16 from own I7
  into line 2 legal at X38 and X30, not at X20/X26/X14/X34/X12) — wire indices are column-phase dependent,
  so wire codes must be keyed by the wire's own position, not just by the LAB. Partial chains (fitter to
  complete the rest) are rejected.
- fuzz/wire_codes.json: chain codes, so far 1: LE_BUFFER I7 -> R4 I16 -> line 2 = (-18,12)+(-17,12)+(14,9)
  (one LAB only). bl3's C4 chain (LE_BUFFER@0,-1 I31 -> C4 I11 -> line 3) is legal everywhere tried but its
  code does not show in a forced-vs-natural diff (natural route = forced); needs a base where the line is
  unused, which the fixed wiring makes hard.
- tools/routing_model.py — API for tools/pnr/ (keep stable):
    m = RoutingModel()
    m.lut(x, y, n, mask) / m.lut_input(dst, src) / m.local_line(x, y, k, src) / m.wire_chain(buf, wire, line)
    m.hops_to_bits([(a, b), ...]) -> ({(frame, byte, bit): value}, [unknown hops])
  Names as in Quartus timing/.rcf reports. Positions absolute (tools/rbf.py). Unknown hops are returned,
  never guessed. Element-plane rules (LE used, output/clock selects, (11,b), frame 8) and the clock tree
  are still applied by tools/blinky_gen.py.
  Self-check (python3 tools/routing_model.py <design dir>): bl2_full 1107/1107, bl3_full 1112/1112,
  bv_00 1105/1105, bv_05 1107/1107 routing bits equal to Quartus; unknown hops = clock tree, clock into a
  local line, and C4 chains.
- bl2_full model-only: still byte-identical. bl3_full model-only: 3 CRAM bits left, all from its C4 chain:
  LAB 31 (14,12) and LAB 30 (19,65) (21,65).
- Coverage: local lines from own LE_BUFFERs (~20 pairs), left/right neighbour links (~30), vertical links
  (2), sweep entries for several C4/R4 -> line hops at one LAB, one R4 chain. NOT yet: general LE_BUFFER ->
  R4/C4/R24/C16 driver codes and wire-to-wire continuations, per wire index and column phase.
- lfsr (24-bit XNOR LFSR, LED0 = s[23]): 1 LUT + 24 DFFs -> 24 LEs (23 route-through LUTs), 3 LABs,
  67 hops, 0 conflicts, every input coded -> work/pnr_lfsr_model_only.rbf. simcheck 5000 cycles 0
  mismatches; qcheck: placement accepted, the real LUT equal 1/1 (Quartus absorbs the 23 route-throughs).
- burst.v (counter + registered c[23]&c[21]): no legal placement with the decoded vertical links.
- FF power-up values: registers power up at 0; pnr.py refuses a Verilog initial value of 1
  (power-up high is not decoded), hence the XNOR LFSR.

## The 5 board-bisected bits (pnr_cnt24, 2026-11-26)
Board bisection (pnr_cnt24 at LABs (38,30..32), Quartus routing + our models did not run; these 5 bits fixed it):
- (1840,64,0) (1841,65,0) = LAB 31 (-18,67) + (-17,66): local line 29 driven by the VERTICAL link from the
  LAB below (LE_BUFFER I1 of (38,30)). li_struct had an EMPTY code for "29|LE_BUFFER@0,-1_I1" (the forced and
  natural routes were the same, so the force diff showed nothing). Measured against tied bases
  (force3 natural build vs datab tied to 0, source kept alive by a pin) at (20,10) (30,25) (12,6):
  common code (-18,67)+(-17,66) -> fuzz/vbelow_code.json, folded into li_struct.
- (1840,148,0) (1841,149,0) (1845,157,0) = LAB 32 (-18,53) + (-17,52) + (-13,44): the chain own LE_BUFFER I22
  -> R4 I11 -> local line 35 (driver (-18,53)+(-17,52), line (-16,45)+(-13,44)); force3 at (38,20) (38,10)
  (30,20) identical -> fuzz/wire_codes.json (applied by blinky_gen; routing_model.wire_chain).
- The 2 "(11,-2)" clock bits came from a stale clock.json "lab" entry ((11,-2) = 1 is N0's clock-pair select,
  set properly by the (11, b) rule); removed from blinky_gen.
Results: pnr_cnt24_q model-only == Quartus (byte-identical); bl2_full still identical; bl3_full 3 bits (C4 chain).
pnr_cnt24 / pnr_lfsr regenerated with OUR routing (tools/pnr/pnr.py): every local line they use has a 2-bit
structural code (incl. the vertical-below link, used by both). Lesson: an empty forced-probe code means
"not measured", not "all zero" — measure such pairs against a tied base.

## General inter-LAB decode, first attempt (2026-11-26) — random harvesting does not converge
- tools/wire_harvest.py: 200 naturally routed single-net designs (source FF -> LUT datab in another LAB of
  X30..41 x Y24..33), route from the .rcf, on-bits vs a base without the source/net, minus element-plane
  positions; per-hop codes by intersection with explained-bit subtraction; 80/20 hold-out.
- Result: 675 distinct hops (LE_BUFFER>C4 116, C4>R4 89, R4>LOCAL_INTERCONNECT 94, C4>LOCAL_INTERCONNECT
  62, R4>R4 57, C4>C4 50, LE_BUFFER>R4 40, R4>C4 34, C16 2), but only 12 occur twice even with relative
  keys (destination column exact, row phase y%4, source as offset). No held-out route is fully covered,
  so there is no accuracy figure; random pairs are too diverse (wire index x position) to repeat.
- Infrastructure in place for when codes exist: routing_model.wire_hop(a, b) (fuzz/wire_hops.json),
  hops_to_bits uses it; blinky_gen emits WIREHOP bits; tools/pnr/pnr.py routes through fully decoded
  chains (fuzz/wire_chains.json, CHAINS/REACH, "wire" option, wires as owned resources) and its placer
  treats LAB pairs with a decoded chain as connected (backup: tools/pnr/pnr.py.bak_wires).
- lfsr_slow still fails to place ("needs an undecoded inter-LAB path"): only 4 decoded chains.
- Next (targeted, should converge): enumerate the chains Quartus uses inside one column stack
  (x = 38, y = 26..34) — LE_BUFFER -> C4 -> LOCAL_INTERCONNECT between rows y and y +/- 1..4 — and
  replicate each relative chain with force3_probe at >= 3 rows of the same y%4 phase. That gives the
  router vertical reach of 4 rows with few distinct codes (C4 index x source buffer x line).

## Open P&R: input pins and LED1-7 (tools/pnr/io_probe.py, 2026-11-26)
Pins (DE0-Nano manual): KEY0 J15, KEY1 E1 (debounced, active low), SW0-3 M1 T8 B9 M15, LED0-7 A15 A13 B13
A11 D1 F3 B1 L3, clock R8, all 3.3-V LVTTL.
- Each pin has a fixed slot LE in LAB (38,30): inputs J15 E1 M1 T8 B9 M15 at N2..N12 (pin -> LUT port ->
  FF), LEDs A13 B13 A11 D1 F3 B1 L3 at N14..N26 (slot FF -> pin). LED0 keeps (38,31) N2/FF N3.
- Measured TOGETHER in one Quartus design (`io_probe.py --all`, work/io_all) so the pin routes don't
  collide: single-pin probes put E1, M1 and B9 all on local line I1. Bundle table fuzz/io_paths_all.json:
  166 CRAM + 120 periphery bits = the bits where the models differ from Quartus's build of io_all, with
  Quartus's values. Input routes (from top.rcf): J15 line 26, E1 3, M1 16, T8 9, B9 12, M15 11, all into
  LUT port datad. (fuzz/io_paths.json = single-pin probes; output entries there are contaminated by an
  undecoded cross-LAB route in the probe design; not used.) io_paths_all_lab32.json = an earlier bundle
  with the LED slots in LAB (38,32); not used (two LABs away from the inputs).
- pnr.py: `--pins file` ('port[bit] PIN'); every input pin gets an inserted register at its slot (+1
  cycle); an output driven by a design register gets that register placed at the LED slot (no extra
  cycle), else an output register is inserted; if that can't be placed, retry with insertion everywhere.
  When the bundle is used, all 13 slots are reserved and all six input lines are owned by their pins.
  emit.py = blinky_gen.py (model-only) + the whole bundle -> work/<name>_open.rbf.
- Placer: start temperature 2000 (PNR_T0) so the 500/1000 vertical-link penalties can be crossed;
  attempts PNR_ATTEMPTS (25).
Results (no Quartus in the flow; not board-tested):
- sw_led (LED0 = ~KEY0, LED1..4 = SW0..3 registered): 7 LUTs/10 DFFs -> 11 LEs, LABs (38,30),(38,31),
  15 hops, 0 conflicts -> work/pnr_sw_led_open.rbf. simcheck2 (vs Yosys netlist, random inputs, latency
  accounted) 4000 cycles 0 mismatches.
- key_toggle (KEY0 press toggles LED0): 4 LEs, 11 hops, 0 conflicts -> work/pnr_key_toggle_open.rbf.
  simcheck2 4000 cycles 0 mismatches.
- qcheck2: Quartus accepts our placement + pins; the real LUTs match (Quartus turns route-throughs into
  feeders or feeds the FF directly). Models + bundle on Quartus's own routing of the same placement are
  NOT byte-identical: the bundle drives all 13 pins (Quartus's build only the used ones) and Quartus
  routes pins differently per design. Bits outside the bundle's positions: key_toggle 1 ((1841,96,0)),
  sw_led 35 (long pin routes in far columns: Quartus chose other routes than in io_all).
Limits: one fixed slot per pin (all in LAB (38,30)); the bundle always configures all 13 pins (unused LEDs
are driven by empty slot FFs = 0, i.e. off); +1 cycle on inputs; LED0's path is always emitted by the
models even if unused; KEY1 (E1) is a clock-capable pin (route starts at CLK_BUFFER) but is used as data.

## Open P&R: power-up high and carry chains (2026-11-26)
Power-up high (`reg x = 1'b1`):
- There is no init bit: Quartus reports "NOT Gate Push-Back" and implements x = 1 as a power-up-0 register
  holding ~x (work/pu_hi: dffeas power_up "low", LUT computes ~x_next, the pin reads it as `.i(!x~q)`).
- pnr.py push_back(): such registers store ~x; the LUT on D is inverted (or an inverter added), every
  LUT reading it has that input inverted in its mask, copying registers read through an inverting
  route-through. An LED driven by it: the register sits at the LED slot and the pin inverts it.
- Output inversion in the I/O cell: one CRAM bit per LED (io_probe.py --inv / --invmap, three
  binary-coded builds): fuzz/io_out_invert.json: A15 (1869,295,0) A11 (1974,295,0) B13 (2265,295,0)
  A13 (2279,295,0), F3 (8,40,1) L3 (8,80,5) B1 (8,198,1) D1 (8,283,2).
Carry chains (arithmetic mode), from Quartus's own counter masks (work/ar_rtl, ar_rtl2):
- cin takes datac's place; datad is left unconnected (reads 1); combout = mask[8 + a + 2b + 4cin],
  cout = mask[a + 2b + 4cin]. Quartus alternates carry polarity along the chain counted from its start
  (LE i: cout inverted for odd i, cin inverted for even i >= 2), whatever the start position (chains starting
  at k = 0, 1, 3, 5, 9 all follow it), so there is no position-dependent inversion in the silicon.
- Chain runs N0 -> N30 in a LAB, then on into N0 of the LAB below (y - 1).
- CRAM: the only arithmetic bit is (-1, LEOFF[n] + (k even)) = 0 on every LE that takes a carry in (the
  LUT input-C select: datac vs cin); the chain's first LE keeps 1. Probes ar_a/ar_b/ar_c (WYSIWYG chains,
  with/without a LAB crossing) and ar_n (same places, normal mode) separate it from routing bits.
  A chain whose last LE is N30 changes block-level bits (-21, 64/63/56/22/21/14) in the LAB below: pnr
  never ends a chain at N30.
- pnr.py: Yosys keeps $alu as ALUKEEP (tools/pnr/alukeep.v), one arithmetic LE per bit (X/CO outputs
  must be unused); chains are placed first as contiguous runs (fixed members respected: a chain register
  can be an LED register); dataa/datab routed, cin not; masks from the semantics. PNR_PEEL=1 moves bit 0
  out of the chain like Quartus. emit.py clears the cin-select bit and picks the measured clock tree for the
  LAB rows that have registers (an unused LAB's row enable stays off).
- Quartus check: cnt18 (18-bit counter, pure chain, LED0 = c[17]) with our placement: models + chain bit on
  Quartus's routing are BYTE-IDENTICAL to Quartus's bitstream (Quartus swaps dataa/datab on its own routing).
- io_out31 bundle (io_probe.py --out31): LED1..7 at LAB (38,31) N4..N16, next to LED0 (N2), outputs only
  (111 CRAM + 86 periphery bits); pnr.py --bundle out31.
- --place file ('reg[bit] x,y,n') fixes registers; a chain follows a fixed member.
Demos (not board-tested):
- cnt25 (25-bit counter, LED0..7 = c[17..24]): 25 LEs = one chain (LUT-only flow: 31+ LEs for 24 bits)
  -> work/pnr_cnt25_open.rbf; simcheck2 0 mismatches. On Quartus's routing: 27 bits differ (Quartus routes
  the LED pins differently than in the io_out31 measurement).
- pu_rot (pattern 1010_1010 rotating on LED0..7 every 2^24 clocks ~0.34 s, three-stage 14+5+5 prescaler,
  four power-up-high registers): -> work/pnr_pu_rot_open.rbf, LED1/3/5/7 pins inverted. Fast variant
  pu_rot_s (3+2+2 prescaler, same structure) simcheck2: 6000 cycles (~46 rotations) 0 mismatches.

## Fix: pin bundles switched off clock rows (2026-11-26)
cnt25 (out31 bundle) was dark on the board. The bundles are residuals against the MERGED 3-LAB clock tree,
so they contained "row enable = 0" for LABs the probe design didn't clock: io_paths_out31 turns off
(1837,138,0),(1837,145,0) [tree2: LAB (38,32)] and (1837,5,0),(1837,293,1) [tree3: LAB (38,30)];
io_paths_all turns off the two LAB (38,32) bits. cnt25's chain starts in (38,32) -> no clock there.
emit.py now never takes clock-tree positions from a bundle (the design's own tree decides). Changed bits:
cnt25 2, pu_rot 4; sw_led and key_toggle (LABs 30/31 only, board-tested) byte-identical to before.
Still suspect in io_paths_out31: 4 entries at frames -18/-17 in LAB (38,31) block rows 8/12/13 are
local-line driver positions, probably corrections for the probe's own toggle ring rather than pin bits.
cnt25_led0 (two chains 17 + 8 bits, LED0 = bit 24 via the LED0 path, no bundle): Quartus check on its
routing = 1 bit off ((1869,126,0), the (11,b) clock-pair rule for Quartus's LAB_CONTROL_MUX clocking;
our own routing clocks every FF from BLK_CLK_BUF).

## Column-38 vertical chains (2026-11-26) — structure found, codes not yet exact
- tools/col_vert.py record: 108 natural single-net designs in column 38 (source 1..4 rows above/below
  rows 26..33, source LEs N2/N30): 101 use exactly LE_BUFFER -> C4 -> LOCAL_INTERCONNECT, 7 the direct
  vertical links. 38 distinct dest-relative chains; some appear at all 8 rows (phase-free), most at 2.
- Code measurement attempts:
  1. forced build vs a base without the source: 20-29 noisy bits (the source's pin input route differs
     per compile) — unusable;
  2. two re-fits of one compile with an alternative chain: no legal same-source alternative exists
     (each buffer/C4 is fixed-wired, other buffers belong to other LEs);
  3. (current) forced_iso: the source also drives a dummy LUT in its own LAB; variant = re-fit with the
     chain + dummy branch, base = same design with the dest input tied off, re-fitted with the SAME .rcf
     for every net. Per row 10-29 bits; intersection over rows gives cores such as C4 -> line 0 =
     (13,1)+(15,1), C4 driver bits at the source row (frames 19/22, db -280 = 4 rows up, -210 = 3 rows),
     plus (19,-2)/(21,-1) in almost every chain (a base artefact, not the chain).
     Leave-one-out over 27 chains with >= 4 rows: the training core is contained in the held-out row's
     diff in 114/133 cases (86 %); not exact, so no entry was accepted (fuzz/col_vert_38.json empty).
- Likely remaining noise: tying the dest input to 1'b0 lets Quartus simplify the dest LUT and its input
  muxes; next try a base where ld.datab is driven by another existing local signal (same LUT mask), and
  subtract the constant (19,-2)/(21,-1) artefact explicitly.
- Integration is ready: blinky_gen applies col_vert entries (COLV, chain + row phase), pnr.py expands them
  into CHAINS/REACH. lfsr_slow does not place/route yet (no accepted entries).
- 2026-11-26 later: accepted 12 column-38 chains into fuzz/col_vert_38.json: consistent in every
  leave-one-out fold after removing the constant base artefact (19,-2)/(21,-1) (115/133 folds contain the
  core; 12/27 chains pass all folds) AND every core bit is set in each natural Quartus build that used
  that chain (42 builds). Source offsets covered: dy = -1 (phases 0, 2), -2 (phase 3), -3, -4, +3, +4
  (phase-free). routing_model.wire_chain also serves these.
- lfsr_slow still has no routable placement in (38,30..32): the stack needs sources 1-2 rows ABOVE
  (only +3/+4 decoded) and the -1/-2 chains exist only for some row phases; widening the stack needs the
  clock tree of more rows (only (38,30..32) measured).
- 2026-11-26, more chains + clock trees: +2 accepted chains (source 1 row above, any phase; 2 rows above,
  phase 3) -> 14 in fuzz/col_vert_38.json, covering source offsets -4..+4 (some phase-limited).
  Clock trees: a union of single-FF per-row votes does NOT reproduce the measured stack tree (single-FF votes
  pick up output-path bits); pair-set votes do (as clock_tree_pnr.json was built). New:
  fuzz/clock_tree_38_29_30.json (pair vote, tools/clk_rows.py set) and fuzz/clock_tree_stack_29_31.json
  (= pair (29,30) + pair (30,31)). Stack (38,29..31) has only one undecoded LAB pair; lfsr_slow places
  there with cost 530 but is rejected: every decoded C4 chain starts at LE N2 or N30 (the recording used
  only those source slots), so only ~4 of 16 LEs per LAB can drive another LAB. lfsr_slow needs more.
- Next: record + force chains for all 16 source slots (each LE has its own two LE_BUFFERs, fixed-wired to
  different C4 wires) at dy = +-1, +-2 for the stack rows; ~16 x 4 chains x 4 rows, with the same
  leave-one-out + natural-build acceptance.
