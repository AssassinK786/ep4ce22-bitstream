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
