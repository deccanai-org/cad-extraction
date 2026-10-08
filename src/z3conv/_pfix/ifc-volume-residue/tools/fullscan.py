#!/usr/bin/env python3
"""fullscan.py WORKDIR OUT.json [--threads N] - converter fidelity for EVERY part, independent of the census:
exact ifcopenshell B-rep volume (OCC GProp, openings applied, iterator with serialized B-rep output) vs the STEP
read-back volume (step_parts) and the sidecar record. Flags |S/X-1| > 1 % (exact parts) or > 3 % (approx-curved)."""
import sys, os, json, gzip, collections, time, argparse
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
ap = argparse.ArgumentParser(); ap.add_argument('wd'); ap.add_argument('out'); ap.add_argument('--threads', type=int, default=2)
a = ap.parse_args()
T0 = time.time()
wd = a.wd
ifc = next((os.path.join(wd, n) for n in ('hdr.ifc', 'merged.ifc', 'schema.ifc', 'unz.ifc', 'in.bin') if os.path.exists(os.path.join(wd, n))), None)
stp = {}
for l in gzip.open(os.path.join(wd, 'step_parts.jsonl.gz'), 'rt'):
    p = json.loads(l)
    if p.get('pid'):
        stp.setdefault(p['pid'], p)
side = {}
try:
    for p in json.load(open(os.path.join(wd, 'out.step.parts.json')))['parts']:
        side.setdefault(p.get('gid'), p)
except Exception:
    pass
f = ifcopenshell.open(ifc)
SKIP = {'IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcSpace', 'IfcGrid', 'IfcAnnotation', 'IfcVirtualElement'}
prods = [p for p in f.by_type('IfcProduct') if p.is_a() not in SKIP and getattr(p, 'GlobalId', None) in stp]
s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
FN = '/tmp/_fs_%d.brep' % os.getpid()
X = {}
it = ifcopenshell.geom.iterator(s, f, max(1, a.threads), include=prods)
if it.initialize():
    while True:
        sh = it.get()
        try:
            d = sh.geometry.brep_data
            (open(FN, 'wb') if isinstance(d, bytes) else open(FN, 'w')).write(d)
            x = TopoDS_Shape(); breptools.Read(x, FN, BRep_Builder())
            g = GProp_GProps(); brepgprop.VolumeProperties(x, g)
            X[sh.guid] = g.Mass() * 1e9
        except Exception:
            pass
        if not it.next():
            break
rows = []; cnt = collections.Counter(); flagged = []
for p in prods:
    gid = p.GlobalId; s_ = stp.get(gid) or {}; sd = side.get(gid) or {}
    S = s_.get('volume'); x = X.get(gid)
    tags = sd.get('tags') or []
    approx = 'approx-curved' in tags
    if not S or not (s_.get('solids') or 0) or x is None or x <= 0:
        cnt['not_compared'] += 1
        continue
    r = S / x
    lim = 0.03 if approx else 0.01
    k = 'ok' if abs(r - 1) <= lim else ('approx_dev' if approx else 'exact_dev')
    cnt[k] += 1
    if k != 'ok':
        flagged.append({'gid': gid, 'cls': p.is_a(), 'name': p.Name, 'S': S, 'X': round(x, 1), 'S_X': round(r, 4), 'tags': tags,
                        'src': sd.get('src'), 'level': sd.get('level'), 'faces': sd.get('faces'), 'why': sd.get('why'), 'openings': len(getattr(p, 'HasOpenings', None) or [])})
flagged.sort(key=lambda r: -abs(r['S_X'] - 1))
out = {'wd': wd, 'parts': len(prods), 'exact_volumes': len(X), 'counts': dict(cnt), 'flagged': flagged[:400], 'flagged_total': len(flagged), 'sec': round(time.time() - T0, 1)}
json.dump(out, open(a.out, 'w'), indent=0)
print(json.dumps({k: out[k] for k in ('wd', 'parts', 'exact_volumes', 'counts', 'flagged_total', 'sec')}))
