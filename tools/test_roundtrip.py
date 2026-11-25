#!/usr/bin/env python3
"""Patch LUT bits into the base bitstream and require a byte-exact match with Quartus."""
import sys, glob; sys.path.insert(0, __file__.rsplit('/',1)[0]); from rbf import Rbf
# LCCOMB_X20_Y10_N0 LUT mask bit -> (frame, byte, bit), from fuzz/x4_lut.json
LUT = {0:(715,133),1:(714,132),2:(715,132),3:(714,133),4:(713,133),5:(712,132),6:(713,132),7:(712,133),
       8:(711,133),9:(710,132),10:(711,132),11:(710,133),12:(709,133),13:(708,132),14:(709,132),15:(708,133)}
def put_mask(r, m):
    for k,(f,b) in LUT.items(): r.set_bit(f,b,5,(m>>k)&1)
base = Rbf.load('work/u_base/top.rbf')
print('checks:', [ (p, Rbf.load(p).check() or 'OK') for p in sorted(glob.glob('work/*/top.rbf'))][:3], '...')
bad = [p for p in glob.glob('work/*/top.rbf') if Rbf.load(p).check()]
print('container check failures across', len(glob.glob('work/*/top.rbf')), 'bitstreams:', bad)
ok = True
for name, m in (('u_m00',0x6997),('u_m15',0x6996^0x8000),('u_base',0x6996)):
    r = Rbf(base.d); put_mask(r, m); r.fix_crcs()
    same = bytes(r.d) == open(f'work/{name}/top.rbf','rb').read()
    print(name, 'byte-exact' if same else 'MISMATCH'); ok &= same
r = Rbf(base.d); r.fix_crcs(); print('fix_crcs is identity on Quartus output:', bytes(r.d)==bytes(base.d))
sys.exit(0 if ok else 1)
