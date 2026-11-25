#!/usr/bin/env python3
"""FF feature bits per LE slot, in LAB-relative coords (dframe from colbase, dbyte from row hibyte, lane)."""
import os,sys,subprocess,json,collections,concurrent.futures as cf
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,R+'/tools'); from rbf import Rbf,F0,FLEN
G=json.load(open(R+'/fuzz/lab_grid.json')); CB={int(k):v for k,v in G['col'].items()}; RW={int(k):v for k,v in G['row'].items()}
PINS=dict(clk='R8',a='M1',b='T8',c='B9',e='M15',en='J15',cl='E16',y='A15')
ONE="1'b1"; ZERO="1'b0"
def design(x,y,n,v):
    s=["module top(input clk,a,b,c,e,en,cl, output y);",
       "  wire w; cycloneive_lcell_comb #(.lut_mask(16'h6996)) l0 (.dataa(a),.datab(b),.datac(c),.datad(e),.combout(w));"]
    if v=='noff': s.append("  assign y=w;")
    else:
        s.append(f"  dffeas #(.power_up(\"low\"),.is_wysiwyg(\"true\")) r0 (.clk({'~clk' if v=='inv' else 'clk'}),.d(w),"
                 f".ena({'en' if v=='ena' else ONE}),.clrn({'~cl' if v=='aclr' else ONE}),.prn(1'b1),"
                 f".sclr({'cl' if v=='sclr' else ZERO}),.sload(1'b0),.asdata(1'b0),.q(y));")
    s.append("endmodule")
    q=[f"set_location_assignment PIN_{p} -to {nm}" for nm,p in PINS.items()]
    q+=[f"set_location_assignment LCCOMB_X{x}_Y{y}_N{n} -to l0",f"set_location_assignment FF_X{x}_Y{y}_N{n+1} -to r0"]
    return '\n'.join(s)+'\n','\n'.join(q)+'\n'
VAR=['noff','ff','inv','ena','aclr','sclr']
locs=[(20,10,n) for n in range(0,32,2)]+[(x,y,n) for (x,y) in ((5,20),(45,3)) for n in (0,14,30)]
jobs=[(x,y,n,v) for (x,y,n) in locs for v in VAR]
def build(j):
    x,y,n,v=j; d=f'{R}/work/f2_{x}_{y}_{n}_{v}'; os.makedirs(d,exist_ok=True)
    a,b=design(x,y,n,v); open(d+'/top.v','w').write(a); open(d+'/extra.qsf','w').write(b)
    if not os.path.exists(d+'/top.rbf'):
        if subprocess.run([R+'/tools/qcompile.sh',d],capture_output=True).returncode: return j,None
    return j,Rbf.load(d+'/top.rbf')
with cf.ThreadPoolExecutor(int(os.environ.get('J','3'))) as ex: res=dict(ex.map(build,jobs))
def rel(x,y,fr,by,bt):
    hb,lane=RW[y]; return (fr-CB[x], hb-by, bt-lane)
def diff(a,b,x,y):
    o=set()
    for i,(p,q) in enumerate(zip(a.d,b.d)):
        if p!=q and i>=F0 and 1<=(i-F0)%FLEN<=295:
            for k in range(8):
                if (p^q)>>k&1: o.add(rel(x,y,(i-F0)//FLEN,(i-F0)%FLEN,k))
    return o
out=collections.defaultdict(dict)
for (x,y,n) in locs:
    for v,ref in (('ff','noff'),('inv','ff'),('ena','ff'),('aclr','ff'),('sclr','ff')):
        A,B=res[(x,y,n,ref)],res[(x,y,n,v)]
        out[f'{x},{y},{n}'][v]=sorted(diff(A,B,x,y)) if A and B else 'FAIL'
json.dump(out,open(R+'/fuzz/ff2.json','w'))
# features common to all LABs for same slot n (n in 0,14,30)
for n in (0,14,30):
    for v in ('ff','inv','ena','aclr','sclr'):
        sets=[set(map(tuple,out[f'{x},{y},{n}'][v])) for (x,y) in ((20,10),(5,20),(45,3)) if out[f'{x},{y},{n}'][v]!='FAIL']
        print(f'N{n:<2} {v:5s} common:',sorted(set.intersection(*sets)) if sets else 'FAIL')
