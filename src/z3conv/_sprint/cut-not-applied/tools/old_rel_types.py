"""Old engines: what do relation records of each type connect? (id1 / id2 classified against the decoded tables)"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old
from db1dec import load
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    byp = {m['pid']: m for m in M}
    o = db1old.Old(data); I, D, F = o.I_all, o.D_all, o.F_all; N = len(I) - 400
    # tables as in db1old.read
    pv = np.zeros(N, bool); pv[:N - 32] = (I[:N - 32] > 0) & (I[4:N - 28] >= 0) & (I[4:N - 28] <= 64)
    for k in (8, 16, 24):
        v = D[k:N - 32 + k]; pv[:N - 32] &= np.isfinite(v) & (np.abs(v) < 1e8)
    pts = {int(I[q]) for q in o.runs(pv, 33)}
    cv = np.zeros(N, bool); Mx = N - 60
    x = np.stack([D[k:Mx + k] for k in (0, 8, 16)], 1); y = np.stack([D[k:Mx + k] for k in (24, 32, 40)], 1)
    with np.errstate(invalid='ignore', over='ignore'):
        cv[:Mx] = (np.abs((x * x).sum(1) - 1) < 0.02) & (np.abs((y * y).sum(1) - 1) < 0.02) & (I[48:Mx + 48] > 0)
    csa = {int(I[q + 48]) for q in o.runs(cv, 53)}
    pos = [m.start() for m in re.finditer(rb'ID[0-9A-F]{8}-[0-9A-F]{4}-', data)]
    objs = {int(I[p - 28]) for p in pos if p > 28 and data[p - 29] == 4}
    def cls(i):
        m = byp.get(i)
        if m is not None:
            return 'cut' if m['cut'] else ('bolt' if m['bolt'] else 'part')
        if i in objs: return 'object_only'
        if i in pts: return 'point'
        if i in csa: return 'csys'
        return 'other'
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    rel = o.runs(rv, 17)
    bt = collections.defaultdict(collections.Counter)
    for q in rel:
        t = int(I[q + 4]); bt[t][(cls(int(I[q + 8])), cls(int(I[q + 12])))] += 1
    print('==', os.path.basename(f)[:16], eng, 'objects', len(objs), 'parts', len(byp))
    for t in sorted(bt, key=lambda t: -sum(bt[t].values())):
        print('   type', t, sum(bt[t].values()), bt[t].most_common(6))
