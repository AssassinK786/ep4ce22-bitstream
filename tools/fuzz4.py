#!/usr/bin/env python3
"""fuzz.py: build variants of one-LUT design, compile in parallel, diff RBF bits vs base."""
import os, sys, subprocess, json, concurrent.futures as cf
PFX=os.environ.get('PFX','');ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL='''module top(input a, input b, input c, input e, output y);
  cycloneive_lcell_comb #(.lut_mask(16'h{mask:04x}), .sum_lutc_input("datac")) l0 (.dataa(a), .datab(b), .datac(c), .datad(e), .combout(y));
endmodule
'''
QSF='''set_location_assignment PIN_M1 -to a
set_location_assignment PIN_T8 -to b
set_location_assignment PIN_B9 -to c
set_location_assignment PIN_M15 -to e
set_location_assignment PIN_A15 -to y
set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l0
'''
def build(name, mask=0x8888, x=20, y=10, n=0):
    d=os.path.join(ROOT,'work',PFX+name); os.makedirs(d,exist_ok=True)
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
    B=int(os.environ.get('BASE','6996'),16)
    jobs=[('base',dict(mask=B))]
    for k in range(16): jobs.append((f'm{k:02d}',dict(mask=B^(1<<k))))
    with cf.ThreadPoolExecutor(int(os.environ.get('J','4'))) as ex:
        res=dict(ex.map(lambda j: build(j[0],**j[1]), jobs))
    base=res['base']; out={}
    for nm,_ in jobs[1:]:
        if res[nm] is None: print(nm,'FAIL'); continue
        db=diffbits(base,res[nm]); out[nm]=db
        F0=7482;body=[x for x in db if x>=F0*8];fb=[(divmod((x//8)-F0,298),x%8) for x in body if ((x//8)-F0)%298<296]
        print(nm,len(db),'data bits:',fb)
    json.dump(out,open(ROOT+'/fuzz/'+PFX+'lut.json','w'))
