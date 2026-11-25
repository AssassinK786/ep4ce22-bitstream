#!/usr/bin/env python3
"""FF / LAB-control fuzz at X20_Y10: LUT N0 -> dffeas N1. Variants add one feature each."""
import os,sys,subprocess,json,concurrent.futures as cf
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,R+'/tools'); from rbf import Rbf,F0,FLEN
PINS=dict(clk='R8',a='M1',b='T8',c='B9',e='M15',en='J15',cl='E16',sd='M2',y='A15')
def design(ff=True,ena=False,aclr=False,sclr=False,sload=False,pwr=False,inv=False,n=0):
    s=[f"module top(input clk,a,b,c,e,en,cl,sd, output y);",
       "  wire w; cycloneive_lcell_comb #(.lut_mask(16'h6996)) l0 (.dataa(a),.datab(b),.datac(c),.datad(e),.combout(w));"]
    if not ff: s.append("  assign y=w;")
    else:
        ONE="1'b1"; ZERO="1'b0"
        s.append(f"  dffeas #(.power_up(\"{'high' if pwr else 'low'}\"),.is_wysiwyg(\"true\")) r0 (.clk({'~clk' if inv else 'clk'}),.d(w),"
                 f".ena({'en' if ena else ONE}),.clrn({'~cl' if aclr else ONE}),.prn(1'b1),"
                 f".sclr({'cl' if sclr else ZERO}),.sload({'en' if sload else ZERO}),.asdata({'sd' if sload else ZERO}),.q(y));")
    s.append("endmodule")
    q=[f"set_location_assignment PIN_{p} -to {nm}" for nm,p in PINS.items()]
    q+=[f"set_location_assignment LCCOMB_X20_Y10_N{n} -to l0",f"set_location_assignment FF_X20_Y10_N{n+1} -to r0"]
    return '\n'.join(s)+'\n','\n'.join(q)+'\n'
V={'noff':dict(ff=False),'ff':{},'ena':dict(ena=True),'aclr':dict(aclr=True),'sclr':dict(sclr=True),
   'sload':dict(sload=True),'pwr':dict(pwr=True),'inv':dict(inv=True),'ff_n2':dict(n=2),'ff_n4':dict(n=4)}
def build(k):
    d=R+'/work/ff_'+k; os.makedirs(d,exist_ok=True); v,q=design(**V[k])
    open(d+'/top.v','w').write(v); open(d+'/extra.qsf','w').write(q)
    if not os.path.exists(d+'/top.rbf'):
        r=subprocess.run([R+'/tools/qcompile.sh',d],capture_output=True,text=True,env=dict(os.environ,EDA='1'))
        if r.returncode: print(k,'FAIL',r.stdout[-400:]); return k,None
    return k,Rbf.load(d+'/top.rbf')
with cf.ThreadPoolExecutor(int(os.environ.get('J','3'))) as ex: res=dict(ex.map(build,V))
def diff(a,b):
    o=[]
    for i,(p,q) in enumerate(zip(a.d,b.d)):
        if p!=q and i>=F0 and 1<=(i-F0)%FLEN<=295:
            o+=[((i-F0)//FLEN,(i-F0)%FLEN,k) for k in range(8) if (p^q)>>k&1]
    return o
out={}
for k,ref in [('ff','noff'),('ena','ff'),('aclr','ff'),('sclr','ff'),('sload','ff'),('pwr','ff'),('inv','ff'),('ff_n2','ff'),('ff_n4','ff')]:
    if res[k] and res[ref]:
        d=diff(res[ref],res[k]); out[k]=d
        near=[t for t in d if 700<=t[0]<=720 and 60<=t[1]<=140]
        print(f'{k:6s} vs {ref:5s}: {len(d):4d} bits, in X20 LAB window: {near}')
json.dump(out,open(R+'/fuzz/ff.json','w'))
