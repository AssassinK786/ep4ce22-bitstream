#!/usr/bin/env python3
"""Map every LAB's N0 LUT to (frame, byte, bit) in one shot: chain of XOR4 LUTs at all legal (X,Y);
variant v_j complements the masks of LUTs whose index has bit j set. Diff decodes LUT index."""
import os,sys,subprocess,json,concurrent.futures as cf
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,R+'/tools'); from rbf import Rbf,F0,FLEN
LEG=[tuple(map(int,l.split())) for l in open(R+'/work/grid/legal.txt')]
N=os.environ.get('NSLOT','0'); H=os.environ.get('HALF','')
if H=='L': LEG=[p for p in LEG if p[0]<=26]
if H=='R': LEG=[p for p in LEG if p[0]>26]
def gen(d,flip):
    os.makedirs(d,exist_ok=True)
    v=["module top(input a, input b, input c, output y);"];prev='a';q=[]
    for i,(x,y) in enumerate(LEG):
        m=0x6996^(0xffff if flip(i) else 0)
        v.append(f"  wire w{i}; cycloneive_lcell_comb #(.lut_mask(16'h{m:04x})) l{i} (.dataa({prev}), .datab(b), .datac(c), .datad(a), .combout(w{i}));")
        q.append(f"set_location_assignment LCCOMB_X{x}_Y{y}_N{N} -to l{i}");prev=f"w{i}"
    v.append(f"  assign y={prev};\nendmodule");open(d+'/top.v','w').write('\n'.join(v)+'\n')
    open(d+'/extra.qsf','w').write("set_location_assignment PIN_M1 -to a\nset_location_assignment PIN_T8 -to b\nset_location_assignment PIN_B9 -to c\nset_location_assignment PIN_A15 -to y\n"+'\n'.join(q)+'\n')
    if not os.path.exists(d+'/top.rbf'):
        r=subprocess.run([R+'/tools/qcompile.sh',d],capture_output=True,text=True)
        if r.returncode: print(r.stdout[-800:]); return None
    return Rbf.load(d+'/top.rbf')
if __name__=='__main__':
    nb=(len(LEG)-1).bit_length()
    jobs=[('base',lambda i:False),('all',lambda i:True)]+[(f'b{j}',(lambda j: lambda i:(i>>j)&1)(j)) for j in range(nb)]
    W=R+f'/work/gm{N}{H}_'
    with cf.ThreadPoolExecutor(int(os.environ.get('J','3'))) as ex: res=dict(ex.map(lambda j:(j[0],gen(W+j[0],j[1])),jobs))
    if None in res.values(): sys.exit('compile failed')
    b=res['base'].d
    def dbits(o):
        out=set()
        for i,(p,q) in enumerate(zip(b,o.d)):
            if p!=q and i>=F0 and 1<=(i-F0)%FLEN<=295:
                for k in range(8):
                    if (p^q)>>k&1: out.add((i-F0)//FLEN*FLEN*8+((i-F0)%FLEN)*8+k)
        return out
    allb=dbits(res['all']); bs=[dbits(res[f'b{j}']) for j in range(nb)]
    lut={}
    for x in allb:
        idx=sum(1<<j for j in range(nb) if x in bs[j]); lut.setdefault(idx,[]).append(x)
    out={}; bad=0
    for i,(X,Y) in enumerate(LEG):
        bits=sorted(lut.get(i,[]))
        if len(bits)!=16: bad+=1
        out[f'{X},{Y}']=[(z//(FLEN*8),(z%(FLEN*8))//8,z%8) for z in bits]
    print('LUTs',len(LEG),'with 16 bits:',len(LEG)-bad,'diff bits total',len(allb))
    json.dump(out,open(R+f'/fuzz/grid_n{N}{H}.json','w'))
