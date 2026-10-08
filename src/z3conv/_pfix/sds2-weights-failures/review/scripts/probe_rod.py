"""For every TURNED piece whose rings are not found (straight-rod stand-in path), report the diameter the patched
rod_diameter() picks vs the piece's own mesh extent and the name, and the SDS2 weight implied."""
import sys, os, glob, json, math, collections
W='/work/agentwork/sds2-weights-failures-review'
sys.path.insert(0, f'{W}/trees/w553/sds2-step-pipeline/decode')
import numpy as np
import to_step2 as T
from piece_table import read_pieces
from instances import piece_vertices, subm_vertices
mesh_vertices = T.mesh_vertices
out={}
for job in sorted(glob.glob(f'{W}/jobs/*')):
    if job.endswith('_noidx') or not os.path.exists(f'{job}/subm/subm_idx'): continue
    try: P=read_pieces(job)
    except Exception as e: out[os.path.basename(job)]=f'err {e}'; continue
    rows=[]
    for sid,p in P.items():
        if not T.TURNED.match(p['name']) or p['name'].startswith('Conc'): continue
        try:
            V=mesh_vertices(job,sid); Vt=subm_vertices(job,sid)
        except Exception: continue
        segs=T.turned_local(Vt) if Vt is not None and len(Vt)>=6 else None
        if not segs and V is not None: segs=T.turned_local(V)
        if segs or not (p['W']>0 and p['L']>0): continue
        Vx=V if V is not None else Vt
        if Vx is None or not len(Vx): continue
        Vf=piece_vertices(job,sid)
        if Vf is not None and len(Vf)>=4: Vx=Vf
        a=int(np.argmax(np.ptp(Vx,0)))
        d=T.rod_diameter(p,Vx); L=T.rod_length(p,Vx[:,a],d)
        dm=float(np.ptp(Vx,0).min())
        lb=math.pi*d*d/4*L*0.2836
        lb_old=math.pi*p['W']**2/4*p['L']*0.2836
        rows.append(dict(sid=sid,name=p['name'],W=round(p['W'],4),L=round(p['L'],3),wt=round(p['wt'],4),dm=round(dm,4),d=round(d,4),Lr=round(L,3),lb=round(lb,4),ratio=round(lb/p['wt'],3) if p['wt']>0 else None, ratio_v553=round(lb_old/p['wt'],3) if p['wt']>0 else None, name_used=abs(d-dm)>0.15*max(dm,1e-6)))
    out[os.path.basename(job)]=rows
bad=[(j,r) for j,rs in out.items() if isinstance(rs,list) for r in rs if r['name_used'] or (r['ratio'] and not 0.5<r['ratio']<2)]
print('jobs',len(out),'straight-rod pieces',sum(len(v) for v in out.values() if isinstance(v,list)))
for j,r in bad[:60]: print(j[:30], r)
json.dump(out, open(f'{W}/probe_rod.json','w'), indent=0, default=str)
