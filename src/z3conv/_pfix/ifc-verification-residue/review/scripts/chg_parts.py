#!/usr/bin/env python3
"""chg_parts.py LABEL_A LABEL_B ID16... : parts whose level / tags differ between two runs; for each, an independent reference from
the IFC itself (ifcopenshell kernel mesh in LOCAL coordinates: closed? mesh volume) vs the read-back volume of each run"""
import sys, os, json, gzip, re, collections
import numpy as np
import ifcopenshell, ifcopenshell.geom
W = '/work/agentwork/ifc-verification-residue-review'
A, B = sys.argv[1], sys.argv[2]
def parts(l, i):
    d = {}
    p = os.path.join(W, 'w', l, i, 'step_parts.jsonl.gz')
    if not os.path.exists(p): return d
    for line in gzip.open(p, 'rt'):
        r = json.loads(line); k = r.get('pid') or r.get('name') or '#%s' % r.get('i')
        e = d.setdefault(k, {'solids': 0, 'valid': 0, 'volume': 0.0, 'shells': 0, 'desc': r.get('desc') or '', 'name': r.get('name'), 'n': 0})
        e['n'] += 1; e['solids'] += r.get('solids') or 0; e['valid'] += r.get('valid') or 0; e['volume'] += r.get('volume') or 0.0; e['shells'] += r.get('shells') or 0
    return d
def tags(desc):
    m = re.findall(r'\[v6:([^\]]*)\]', desc or '')
    return ' '.join(sorted(set(' '.join(m).replace(',', ' ').split())))
def mesh_ref(f, gid, st):
    try:
        prod = f.by_guid(gid)
    except Exception:
        return {'err': 'guid not found'}
    try:
        sh = ifcopenshell.geom.create_shape(st, prod)
        g = sh.geometry
        V = np.array(g.verts, dtype=float).reshape(-1, 3); F = np.array(g.faces, dtype=np.int64).reshape(-1, 3)
        # weld coincident vertices (kernel output may duplicate per face)
        key = np.round(V / 1e-7).astype(np.int64)
        _, inv = np.unique(key, axis=0, return_inverse=True); F2 = inv.reshape(-1)[F]
        F2 = F2[(F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 0] != F2[:, 2])]
        e = np.sort(np.concatenate([F2[:, [0, 1]], F2[:, [1, 2]], F2[:, [2, 0]]]), axis=1)
        _, cnt = np.unique(e, axis=0, return_counts=True)
        Vw = _[0:0]
        P = np.array(g.verts, dtype=float).reshape(-1, 3)
        a, b, c = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
        vol = float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0) * 1e9    # m3 -> mm3
        return {'tris': int(len(F)), 'open_edges': int((cnt == 1).sum()), 'nonmanifold_edges': int((cnt > 2).sum()), 'mesh_vol_mm3': round(abs(vol), 1),
                'type': prod.is_a(), 'name': prod.Name}
    except Exception as ex:
        return {'err': f'{type(ex).__name__}: {str(ex)[:150]}'}
st = ifcopenshell.geom.settings()
for k_, v_ in (('use-world-coords', False), ('weld-vertices', False)):
    try: st.set(k_, v_)
    except Exception: pass
res = []
for i in sys.argv[3:]:
    pa, pb = parts(A, i), parts(B, i)
    chg = [k for k in pa if k in pb and (tags(pa[k]['desc']) != tags(pb[k]['desc']) or pa[k]['solids'] != pb[k]['solids'])]
    miss = [k for k in pa if k not in pb]; extra = [k for k in pb if k not in pa]
    f = None
    inp = os.path.join(W, 'in', i + '.bin')
    if chg and os.path.exists(inp):
        try:
            f = ifcopenshell.open(inp)
        except Exception as ex:
            f = None
    for k in chg[:int(os.environ.get("CHG_MAX", "60"))]:
        r = {'id': i, 'pid': k, 'name': pa[k]['name'], A: {x: pa[k][x] for x in ('solids', 'valid', 'shells')}, B: {x: pb[k][x] for x in ('solids', 'valid', 'shells')},
             A + '_tags': tags(pa[k]['desc']), B + '_tags': tags(pb[k]['desc']), A + '_vol': round(pa[k]['volume'], 1), B + '_vol': round(pb[k]['volume'], 1)}
        if f is not None:
            r['ifc_kernel_local'] = mesh_ref(f, k, st)
            mv = (r['ifc_kernel_local'] or {}).get('mesh_vol_mm3')
            if mv:
                r[B + '_vol_over_kernel'] = round(pb[k]['volume'] / mv, 5) if pb[k]['volume'] else None
        res.append(r)
    print(json.dumps({'id': i, 'changed': len(chg), 'missing_in_' + B: len(miss), 'extra_in_' + B: len(extra)}), flush=True)
for r in res:
    print(json.dumps(r, default=str), flush=True)
