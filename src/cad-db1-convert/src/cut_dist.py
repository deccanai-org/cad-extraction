import sys, json, numpy as np; sys.path.insert(0,'src')
from db1dec import *
L=json.load(open('layouts.json')); V=[v['layout'] for v in L.values() if v.get('layout')]
def segdist(a0,a1,b0,b1):
    # min distance between segments (sampled)
    ts=np.linspace(0,1,21)
    A=a0+np.outer(ts,a1-a0); B=b0+np.outer(ts,b1-b0)
    return float(np.min(np.linalg.norm(A[:,None,:]-B[None,:,:],axis=2)))
for tag, eng in [a.split(':') for a in sys.argv[1:]]:
    db,pts,cs,lay=decode(f'pairs/data/{tag}.db1',L[eng]['layout'],V,False)
    M=members(db,pts,cs,lay); links=db.find_cut_links(M)
    by={m['seq']:m for m in M}
    d=[]
    for p,cl in links.items():
        if p not in by: continue
        for c in cl:
            if c in by: d.append(segdist(by[p]['O'],by[p]['E'],by[c]['O'],by[c]['E']))
    d=np.array(d)
    print(tag, 'links', len(d), 'dist percentiles 50/90/99/max', [round(float(np.percentile(d,q)),1) for q in (50,90,99,100)] if len(d) else None)
