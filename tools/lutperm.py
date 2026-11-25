import json,re,glob,os
geo=json.load(open('fuzz/le_geom.json'))
LOG={'a':0,'b':1,'c':2,'e':3}
def perm(d):
    s=open(d+'/simulation/modelsim/top.vo').read()
    blk=s[s.index('cycloneive_lcell_comb l0('):]; blk=blk[:blk.index(');')]
    p={}
    for i,pin in enumerate('abcd'):
        m=re.search(r'\.data'+pin+r'\(\\(\w)~input_o',blk)
        if m: p[LOG[m.group(1)]]=i
    return p
def phys(k,p): return sum(((k>>l)&1)<<p[l] for l in range(4))
res={}
for t,e in geo.items():
    try: p=perm(f'work/{t}_b')
    except Exception as ex: print(t,'no vo',ex); continue
    col0=min(f for v in e.values() if v!='FAIL' for f,_,_ in v)
    row=max(b for v in e.values() if v!='FAIL' for _,b,_ in v)
    m={phys(int(k),p):(f-(col0+0), row-b) for k,v in e.items() if v!='FAIL' for f,b,_ in v}
    res[t]=m; print(t,'perm',p,'phys->(dframe,dbyte)',dict(sorted(m.items())))
