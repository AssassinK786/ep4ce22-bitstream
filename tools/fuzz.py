#!/usr/bin/env python3
"""fuzz.py: build variants of one-LUT design, compile in parallel, diff RBF bits vs base."""
import os, sys, subprocess, json, concurrent.futures as cf
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL='''module top(input a, input b, output y);
  cycloneive_lcell_comb #(.lut_mask(16'h{mask:04x}), .sum_lutc_input("datac")) l0 (.dataa(a), .datab(b), .datac(1'b0), .datad(1'b0), .combout(y));
endmodule
'''
QSF='''set_location_assignment PIN_M1 -to a
set_location_assignment PIN_T8 -to b
set_location_assignment PIN_A15 -to y
set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l0
'''
def build(name, mask=0x8888, x=20, y=10, n=0):
    d=os.path.join(ROOT,'work',name); os.makedirs(d,exist_ok=True)
    open(d+'/top.v','w').write(TPL.format(mask=mask))
    open(d+'/extra.qsf','w').write(QSF.format(x=x,y=y,n=n))
    if not os.path.exists(d+'/top.rbf'):
        r=subprocess.run([ROOT+'/tools/qcompile.sh',d],capture_output=True,text=True)
        if r.returncode: return name,None
    return name,open(d+'/top.rbf','rb').read()
def diffbits(a,b):
    out=[]
    for i,(p,q) in enumerate(zip(a,b)):
        x=p^q
        while x:
            k=(x&-x).bit_length()-1; out.append(i*8+k); x&=x-1
    return out
if __name__=='__main__':
    jobs=[('base',{})]
    for k in range(16): jobs.append((f'm{k:02d}',dict(mask=0x8888^(1<<k))))
    for nm,kw in [('pX21',dict(x=21)),('pY11',dict(y=11)),('pN2',dict(n=2)),('pN4',dict(n=4))]: jobs.append((nm,kw))
    with cf.ThreadPoolExecutor(int(os.environ.get('J','4'))) as ex:
        res=dict(ex.map(lambda j: build(j[0],**j[1]), jobs))
    base=res['base']; out={}
    for nm,_ in jobs[1:]:
        if res[nm] is None: print(nm,'FAIL'); continue
        db=diffbits(base,res[nm]); out[nm]=db
        print(nm, len(db), db[:12])
    json.dump(out,open(ROOT+'/fuzz/lut1.json','w'))
