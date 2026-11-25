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
