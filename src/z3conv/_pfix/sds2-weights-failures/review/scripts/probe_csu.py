import sys, os, glob, csv, collections
W='/work/agentwork/sds2-weights-failures-review'
sys.path.insert(0, f'{W}/trees/w553/sds2-step-pipeline/decode')
import numpy as np
from piece_table import read_pieces
from sds2job import read_shapes
from instances import piece_vertices
job=glob.glob(f'{W}/jobs/15-027_CSU_JOB_347cb7')[0]
P=read_pieces(job); S=read_shapes(job)
sk=list(csv.DictReader(open(glob.glob(f'{W}/out/w553/347cb74ff25176a0a77f5aaf/*_skipped.csv')[0])))
seen=set()
for r in sk:
    sid=int(r['piece'])
    if sid in seen: continue
    seen.add(sid)
    p=P[sid]; sh=S.get(p['sec'])
    V=piece_vertices(job,sid)
    ext=np.sort(np.ptp(V,0))[::-1].round(2).tolist() if V is not None and len(V) else None
    cat=(sh.weight*p['L']/12) if sh is not None else None
    print(sid, p['name'], 'L', round(p['L'],2), 'wt', round(p['wt'],2), 'catalog', round(cat,1) if cat else None, 'sec', sh.name if sh else None, 'face-vertex extents', ext)
