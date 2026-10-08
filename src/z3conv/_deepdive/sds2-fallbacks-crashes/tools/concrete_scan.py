"""Concrete pieces ("Conc..."): does the piece file hold a closed B-rep (as stored / after the keyhole split), and how
does its volume compare with the v4/v5 prism (concrete_local) and with SDS2's weight at 150 pcf?
usage: concrete_scan.py <decode dir> <job> [--patched <patched decode dir>]"""
import sys, os, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import brep, to_step2 as T2
from piece_table import read_pieces
from instances import material_instances
from sds2job import read_members
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
job = sys.argv[2]
P = read_pieces(job)
def vol(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); return abs(g.Mass()) / MM ** 3
def split_loops(f):
    out, cur = [], []
    for i in f:
        if cur and i == cur[-1]: continue
        if i in cur:
            j = cur.index(i); seg = cur[j:]; cur = cur[:j + 1]
            if len(seg) >= 3: out.append(seg)
        else: cur.append(i)
    if len(cur) >= 3 and cur[0] == cur[-1]: cur = cur[:-1]
    return ([cur] if len(cur) >= 3 else []) + out
def encode(loops):
    nf = []
    for l in loops: nf += l + ([l[0]] if len(loops) > 1 else [])
    return nf
# one placement per concrete piece (for concrete_local's vertical axis)
mems, _ = read_members(job); pl = {}
for m in mems:
    try: _, inst = material_instances(job, m.id, P)
    except Exception: continue
    for sid, M, o in inst:
        if sid in P and P[sid]['name'].startswith('Conc'): pl.setdefault(sid, (M, o))
c = collections.Counter(); rows = []
for sid, p in P.items():
    if not p['name'].startswith('Conc'): continue
    fp = os.path.join(job, 'subm', str(sid))
    if not os.path.exists(fp): c['no piece file'] += 1; continue
    data = open(fp, 'rb').read(); r = brep.parse(data)
    if r is None: c['no face topology'] += 1; continue
    V, F = r
    s1 = brep.solid(V, F)
    s2 = s1 if s1 is not None else brep.solid(V, [encode(split_loops(f)) for f in F])
    used = sorted({i for f in F for i in f}); Vall = V
    prism_v = None
    if sid in pl:
        M, o = pl[sid]
        lohi = T2.concrete_local(T2.mesh_vertices(job, sid) if T2.mesh_vertices(job, sid) is not None else V, p, M)
        if lohi: prism_v = float(np.prod(lohi[1] - lohi[0]))
    vb = vol(s2) if s2 is not None else None
    wt_v = p['wt'] / 150 * 1728 if p['wt'] > 0 else None          # in3 at 150 pcf
    st = 'closed as stored' if s1 is not None else 'closed after keyhole split' if s2 is not None else 'open'
    c[st] += 1
    rows.append((sid, p['name'], round(p['L'], 2), round(p['W'], 2), round(p['T'], 2), st, vb and round(vb), prism_v and round(prism_v), wt_v and round(wt_v),
                 'unused verts %d/%d' % (len(V) - len(used), len(V)), 'ext(faces)', np.round(np.ptp(V[used], 0), 2).tolist(), 'ext(all)', np.round(np.ptp(V, 0), 2).tolist()))
print(os.path.basename(job), dict(c))
print('sid, name, L, W, T, status, brep in3, prism in3, SDS2 wt@150pcf in3, ...')
for x in rows[:40]: print(' ', x)
ok = [x for x in rows if x[6] and x[8]]
if ok:
    rb = np.array([x[6] / x[8] for x in ok]); print('brep/SDS2-weight volume ratio: median %.3f  min %.3f  max %.3f  n %d' % (np.median(rb), rb.min(), rb.max(), len(rb)))
okp = [x for x in rows if x[7] and x[8]]
if okp:
    rp = np.array([x[7] / x[8] for x in okp]); print('prism/SDS2-weight volume ratio: median %.3f  min %.3f  max %.3f  n %d' % (np.median(rp), rp.min(), rp.max(), len(rp)))
