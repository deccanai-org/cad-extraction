#!/usr/bin/env python3
"""truth.py WD OUT.json [--max N] - for a census-v3 work dir (src_parts = v3): rerun kit census v2 on the same input, find
the parts whose volume verdict differs (v2 outside -> v3 in-band or no expectation; v2 in -> v3 outside) and compare their
STEP read-back volume with the EXACT kernel B-rep volume (ifcopenshell, openings applied, OCC GProp). If STEP == exact
(<= 1 %, 3 % approx-curved) the v3 clearing is justified; otherwise v3 hides a real converter deviation."""
import sys, os, json, gzip, subprocess, collections, argparse, time, random
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
ap = argparse.ArgumentParser(); ap.add_argument('wd'); ap.add_argument('out'); ap.add_argument('--max', type=int, default=400)
a = ap.parse_args()
T0 = time.time()
W = '/work/agentwork/ifc-volume-residue-review'
sys.path.insert(0, f'{W}/pkg/kit2')
import grade_join as G
wd = a.wd
ifc = next((os.path.join(wd, n) for n in ('hdr.ifc', 'merged.ifc', 'schema.ifc', 'unz.ifc', 'in.bin') if os.path.exists(os.path.join(wd, n))), None)
subprocess.run(['/opt/conv/env/bin/python', f'{W}/pkg/ifc_census_v2.py', ifc, f'{wd}/census_v2r.json', '--parts', f'{wd}/src_parts_v2r.jsonl.gz'], capture_output=True)
p2 = {p['gid']: p for p in G.load(f'{wd}/src_parts_v2r.jsonl.gz') if p.get('gid')}
p3 = {p['gid']: p for p in G.load(f'{wd}/src_parts.jsonl.gz') if p.get('gid')}
step = {}
for s in G.load(f'{wd}/step_parts.jsonl.gz'):
    if s.get('pid') and (s.get('solids') or 0) > 0:
        step.setdefault(s['pid'], s)


def verdict(p, s):
    v = s.get('volume'); e = G.expected_volume(p) if p else None
    if not v or not e or e <= 0:
        return None, None
    r = v / e
    if abs(r - 1) <= 0.05:
        return 'in', r
    if p.get('an') and p.get('pt') in G.CURVED:
        return ('in' if G.CURVED_BAND[0] <= r <= G.CURVED_BAND[1] else 'out'), r
    return 'out', r


cleared = []; newout = []
for g, s in step.items():
    a2, r2 = verdict(p2.get(g), s); a3, r3 = verdict(p3.get(g), s)
    if a2 == 'out' and a3 != 'out':
        cleared.append((g, r2, r3, (p3.get(g) or {}).get('qx') or ('an' if (p3.get(g) or {}).get('an') else 'q')))
    if a3 == 'out' and a2 != 'out':
        newout.append((g, r2, r3, (p3.get(g) or {}).get('qx') or ('an' if (p3.get(g) or {}).get('an') else 'q')))
random.seed(1)
samp = cleared if len(cleared) <= a.max else random.sample(cleared, a.max)
need = {x[0] for x in samp} | {x[0] for x in newout}
f = ifcopenshell.open(ifc)
prods = [f.by_guid(g) for g in need]
prods = [p for p in prods if p is not None]
X = {}
if prods:
    s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
    FN = '/tmp/_truth_%d.brep' % os.getpid()
    it = ifcopenshell.geom.iterator(s, f, 2, include=prods)
    if it.initialize():
        while True:
            sh = it.get()
            try:
                d = sh.geometry.brep_data
                (open(FN, 'wb') if isinstance(d, bytes) else open(FN, 'w')).write(d)
                x = TopoDS_Shape(); breptools.Read(x, FN, BRep_Builder())
                gp = GProp_GProps(); brepgprop.VolumeProperties(x, gp); X[sh.guid] = gp.Mass() * 1e9
            except Exception:
                pass
            if not it.next():
                break


def rows(lst):
    out = []; c = collections.Counter()
    for g, r2, r3, basis in lst:
        S = step[g]['volume']; x = X.get(g)
        approx = 'approx-curved' in (step[g].get('desc') or '')
        if x is None or x <= 0:
            c['no_exact'] += 1; k = None
        else:
            k = 'faithful' if abs(S / x - 1) <= (0.03 if approx else 0.01) else 'deviates'
            c[(basis, k)] += 1
        out.append([g, (p3.get(g) or {}).get('name'), basis, round(r2, 4) if r2 else None, round(r3, 4) if r3 else None,
                    round(S / x, 4) if x else None, k])
    return out, {str(k): v for k, v in c.items()}


cr, cc = rows(samp); nr, nc = rows(newout)
res = {'wd': wd, 'cleared': len(cleared), 'cleared_checked': len(samp), 'cleared_counts': cc,
       'cleared_deviating_ex': [r for r in cr if r[-1] == 'deviates'][:30], 'new_outside': len(newout), 'new_outside_counts': nc,
       'new_outside_ex': nr[:30], 'sec': round(time.time() - T0, 1)}
json.dump(res, open(a.out, 'w'), indent=0, default=str)
print(json.dumps({k: res[k] for k in ('wd', 'cleared', 'cleared_checked', 'cleared_counts', 'new_outside', 'new_outside_counts', 'sec')}, default=str))
