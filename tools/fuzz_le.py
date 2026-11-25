#!/usr/bin/env python3
"""LUT-bit geometry fuzz: per location, base XOR4 + single mask-bit flips; outputs data-bit diffs."""
import os, sys, json, concurrent.futures as cf, importlib.util
sys.path.insert(0, os.path.dirname(__file__)); from rbf import Rbf, F0, FLEN
spec=importlib.util.spec_from_file_location('f4',os.path.join(os.path.dirname(__file__),'fuzz4.py')); f4=importlib.util.module_from_spec(spec); spec.loader.exec_module(f4)
B=0x6996; BITS=[0,1,2,4,8,15]
locs=[(20,10,n) for n in range(0,32,2)]+[(x,10,0) for x in (19,21,22,23,24)]+[(20,y,0) for y in (9,11,12,13,20,1)]
jobs=[]
for (x,y,n) in locs:
    t=f'le_{x}_{y}_{n}'
    jobs.append((t+'_b',B,x,y,n)); jobs+= [(f'{t}_m{k:02d}',B^(1<<k),x,y,n) for k in BITS]
def run(j): nm,m,x,y,n=j; return nm,f4.build(nm,mask=m,x=x,y=y,n=n)[1]
with cf.ThreadPoolExecutor(int(os.environ.get('J','4'))) as ex: R=dict(ex.map(run,jobs))
out={}
for (x,y,n) in locs:
    t=f'le_{x}_{y}_{n}'; b=R[t+'_b']
    if b is None: print(t,'BASE FAIL'); continue
    ent={}
    for k in BITS:
        v=R[f'{t}_m{k:02d}']
        if v is None: ent[k]='FAIL'; continue
        dd=[]
        for i,(p,q) in enumerate(zip(b,v)):
            if p!=q and i>=F0:
                fr,o=divmod(i-F0,FLEN)
                if 1<=o<=295:
                    x_=p^q; dd+= [(fr,o,bb) for bb in range(8) if x_>>bb&1]
        ent[k]=dd
    out[t]=ent; print(t,{k:v for k,v in ent.items()})
json.dump(out,open(os.path.join(os.path.dirname(__file__),'..','fuzz','le_geom.json'),'w'))
