import sys, re, json, glob, collections, numpy as np; sys.path.insert(0,'src')
import db1old
from db1dec import load
for f in sorted(glob.glob('pairs/data/old_*.db1')):
    data=load(f); eng=float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut = db1old.read(data, eng)
    # axis agreement: x along p1->p2 is implied by E-O; recompute from stored points
    ag=None
    if M:
        P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
        o = db1old.Old(data)
        # rebuild point table lookup quickly via read() internals is not exposed; use E-O vs xr (always parallel) -> use p1/p2 from record
    print(f.split('/')[-1], eng, 'members', len(M), {k: info[k] for k in ('points','csys','part_attr','polygons','parts','salvaged')}, 'profiles', sum(1 for m in M if m['prof']))
