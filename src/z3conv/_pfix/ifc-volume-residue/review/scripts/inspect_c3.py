#!/usr/bin/env python3
"""inspect_c3.py ID - for a model whose census-v3 outside count rose: per new-analytic part, profile kind + v3 'an' vs exact
kernel B-rep (no STEP needed) and the live STEP part of the same name"""
import sys, os, json, gzip, subprocess, collections
import boto3
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
W = '/work/agentwork/ifc-volume-residue-review'
sys.path.insert(0, f'{W}/pkg/kit2'); import grade_join as G
mid = sys.argv[1]
rows = {o['id'][:16]: o for o in json.load(open(f'{W}/pkg/census_rows.json'))}
o = rows[mid[:16]]
d = f'{W}/insp/{mid[:16]}'; os.makedirs(d, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1')
s3.download_file('bim-proprietary-data', o['input_key'], f'{d}/in.bin')
for v, cen in (('v2', 'ifc_census_v2.py'), ('v3', 'ifc_census_v3.py')):
    subprocess.run(['/opt/conv/env/bin/python', f'{W}/pkg/{cen}', f'{d}/in.bin', f'{d}/c{v}.json', '--parts', f'{d}/p{v}.jsonl.gz'], capture_output=True)
p2 = {p['gid']: p for p in G.load(f'{d}/pv2.jsonl.gz')}; p3 = G.load(f'{d}/pv3.jsonl.gz')
new = [p for p in p3 if p.get('an') and not p2.get(p['gid'], {}).get('an')]
f = ifcopenshell.open(f'{d}/in.bin')
prods = [f.by_guid(p['gid']) for p in new]
s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
X = {}
it = ifcopenshell.geom.iterator(s, f, 2, include=prods)
if prods and it.initialize():
    while True:
        sh = it.get()
        try:
            dd = sh.geometry.brep_data; fn = f'{d}/x.brep'
            (open(fn, 'wb') if isinstance(dd, bytes) else open(fn, 'w')).write(dd)
            x = TopoDS_Shape(); breptools.Read(x, fn, BRep_Builder()); gp = GProp_GProps(); brepgprop.VolumeProperties(x, gp); X[sh.guid] = gp.Mass() * 1e9
        except Exception:
            pass
        if not it.next():
            break
cnt = collections.Counter(); out = []
for p in new:
    x = X.get(p['gid']); e = f.by_guid(p['gid'])
    items = [it for r in e.Representation.Representations if r.RepresentationIdentifier in (None, 'Body', 'Facetation') for it in r.Items]
    it0 = items[0]
    if it0.is_a('IfcMappedItem'):
        it0 = it0.MappingSource.MappedRepresentation.Items[0]
    prof = it0.SweptArea if it0.is_a('IfcSweptAreaSolid') else None
    oc = prof.OuterCurve if prof is not None and hasattr(prof, 'OuterCurve') else None
    kind = (prof.is_a() if prof else it0.is_a()) + '/' + (oc.is_a() if oc else '-')
    segs = [sg.ParentCurve.is_a() + ('' if not sg.ParentCurve.is_a('IfcTrimmedCurve') else ':' + sg.ParentCurve.BasisCurve.is_a()) for sg in oc.Segments] if oc is not None and oc.is_a('IfcCompositeCurve') else None
    r = p['an'] / x if x else None
    k = 'match' if r and abs(r - 1) <= 0.01 else ('off' if r else 'noexact')
    cnt[(kind, k)] += 1
    out.append([p['gid'], p['name'], kind, segs[:8] if segs else None, p['an'], round(x, 1) if x else None, round(r, 4) if r else None])
print(json.dumps({'id': mid, 'new_an': len(new), 'counts': {str(k): v for k, v in cnt.items()}}))
for x in sorted(out, key=lambda z: -abs((z[-1] or 1) - 1))[:15]:
    print(json.dumps(x))
