"""validate decoded bolt groups against a Tekla IFC export (GUID join). -> JSON summary
   validate_bolts.py DB1 IFC [out.json]"""
import sys, json, collections, numpy as np, ifcopenshell
import ifcopenshell.util.element as ue
from cache import *
from guid2 import guid_keys
from db1bolts2 import BoltDecoder
import ifcbolts, truthmesh
db1, ifc = sys.argv[1:3]
db, pts, cs, lay, M = get(db1)
bd = BoltDecoder(db, pts, cs, lay)
G = bd.decode(M)
bys = {g['seq']: g for g in G}
GK, back, top = guid_keys(db, np.array(sorted(bys), np.int64) if bys else None)
f = ifcopenshell.open(ifc)
res = collections.Counter(); attr = collections.Counter(); ex = []
TB = {}
try:
    _, GR = ifcbolts.bolts(ifc, True); TB = {g['guid']: g for g in GR}
except Exception: pass
for e in f.by_type('IfcMechanicalFastener'):
    t = (e.Tag or '')[2:38].upper(); res['ifc_groups'] += 1
    k = GK.get(t)
    if k is None: res['no_guid'] += 1; continue
    g = bys.get(k)
    if g is None: res['not_decoded'] += 1; continue
    res['joined'] += 1
    ps = {}
    for kk, v in ue.get_psets(e).items():
        if 'Bolt' in kk or 'Fastener' in kk: ps.update(v)
    d = float(e.NominalDiameter or 0); L = float(e.NominalLength or 0)
    attr[('d', abs(g['d'] - d) < 0.05)] += 1
    fb = g.get('flagbits') or {}
    if fb.get('bolt', True): attr[('L', abs(g['L'] - L) < 0.1)] += 1
    hd = ps.get('Bolt hole diameter')
    if hd: attr[('hole', abs(g['d'] + (g['tol'] or 0) - hd) < 0.06)] += 1
    for kk, nm in (('Slotted hole x', 'slot_x'), ('Slotted hole y', 'slot_y')):
        if ps.get(kk) is not None and g.get(nm) is not None: attr[(nm, abs(g[nm] - ps[kk]) < 0.06)] += 1
    nb = len(g['uv'])
    if ps.get('Washer count') is not None and fb: attr[('washers', (fb['w1'] + fb['w2'] + fb['w3']) * nb == ps['Washer count'])] += 1
    if ps.get('Nut count') is not None and fb: attr[('nuts', (fb['n1'] + fb['n2']) * nb == ps['Nut count'])] += 1
    # positions
    tb = TB.get(t)
    if tb and tb['bolts'] and fb.get('bolt', True):
        T = np.array([[(b['start'] - g['O']) @ g['x'], (b['start'] - g['O']) @ g['y']] for b in tb['bolts']])
        P = np.array(g['uv'])
        if len(T) != len(P): res['count_mismatch'] += 1
        D = np.linalg.norm(P[:, None] - T[None], axis=2)
        okb = (D.min(1) < 1.0)
        res['bolts'] += len(P); res['bolts_xy_ok'] += int(okb.sum())
        res['groups_exact' if okb.all() and len(T) == len(P) else 'groups_off'] += 1
        # axis
        ax_ok = all(abs(abs(b['axis'] @ g['z']) - 1) < 1e-3 for b in tb['bolts'])
        res[('axis_along_z', ax_ok)] += 1
        res[('axis_minus_z', all(b['axis'] @ g['z'] < -0.999 for b in tb['bolts']))] += 1
        if g.get('zc') is not None and g.get('grip') is not None:
            zh = float(np.mean([(b['start'] - g['O']) @ g['z'] for b in tb['bolts']]))
            res[('head_z=zc+grip/2', abs(g['zc'] + g['grip'] / 2 - zh) < 0.5)] += 1
    else:
        try:
            V = truthmesh.mesh(e)
            okc, n, expl = truthmesh.check(V, g['O'], g['x'], g['y'], g['uv'], d)
            res['bolts'] += n; res['bolts_xy_ok'] += okc
            res['groups_exact' if okc == n else 'groups_off'] += 1
        except Exception:
            res['mesh_fail'] += 1
out = dict(db1=db1.split('/')[-1], engine=db.b[7:12].decode('latin1').strip(), decoder={str(k): v for k, v in bd.stats.items()}, guid_back=back,
           result={str(k): v for k, v in res.items()}, attributes={f'{k[0]}:{k[1]}': v for k, v in attr.items()})
print(json.dumps(out, indent=1, default=str))
if len(sys.argv) > 3: json.dump(out, open(sys.argv[3], 'w'), indent=1, default=str)
