#!/usr/bin/env python3
"""insp_an.py ID16 OUT.json - a live class-1 row where census v3 reports outside parts that v2 did not: which parts get a new
v3 expectation (an / q rebased / q dropped), and how that expectation compares with the EXACT kernel B-rep volume of the
product (ifcopenshell create_shape, openings applied) and with the live STEP part of the same name."""
import sys, os, json, gzip, subprocess, collections, time
import boto3
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
T0 = time.time()
i16, outp = sys.argv[1:3]
W = '/work/agentwork/ifc-volume-residue-review'
sys.path.insert(0, f'{W}/pkg/kit2')
import grade_join as G
rows = json.load(open(f'{W}/pkg/census_rows.json'))
o = next(r for r in rows if r['id'].startswith(i16))
s3 = boto3.client('s3', region_name='ap-south-1')
d = f'{W}/insp/{i16}'; os.makedirs(d, exist_ok=True)
s3.download_file('bim-proprietary-data', o['input_key'], f'{d}/in.bin')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
sp = None
for k in (f'{ST}/grade/detail/ifc-{o["id"]}.step_parts.jsonl.gz', f'{ST}/ifc/detail/{o["id"]}.step_parts.jsonl.gz'):
    try:
        s3.download_file(B, k, f'{d}/step_parts.jsonl.gz'); sp = k; break
    except Exception:
        pass
for v in ('v2', 'v3'):
    subprocess.run(['/opt/conv/env/bin/python', f'{W}/pkg/ifc_census_{v}.py', f'{d}/in.bin', f'{d}/c{v}.json', '--parts', f'{d}/p{v}.jsonl.gz'], capture_output=True)
p2 = {p['gid']: p for p in G.load(f'{d}/pv2.jsonl.gz') if p.get('gid')}
p3 = {p['gid']: p for p in G.load(f'{d}/pv3.jsonl.gz') if p.get('gid')}
step = G.load(f'{d}/step_parts.jsonl.gz') if sp else []
byname = collections.defaultdict(list)
for s in step:
    if (s.get('solids') or 0) > 0 and s.get('volume'):
        byname[s.get('name') or s.get('desc')].append(s['volume'])
diff = [g for g in p3 if G.expected_volume(p3[g]) != G.expected_volume(p2.get(g) or {})]
f = ifcopenshell.open(f'{d}/in.bin')
st = ifcopenshell.geom.settings(); st.set('use-world-coords', True); st.set('iterator-output', WR.SERIALIZED)
FN = '/tmp/_insp_%d.brep' % os.getpid()
out = []
for g in diff:
    p = f.by_guid(g)
    x = None
    try:
        sh = ifcopenshell.geom.create_shape(st, p)
        dd = sh.geometry.brep_data
        (open(FN, 'wb') if isinstance(dd, bytes) else open(FN, 'w')).write(dd)
        t = TopoDS_Shape(); breptools.Read(t, FN, BRep_Builder())
        gp = GProp_GProps(); brepgprop.VolumeProperties(t, gp); x = gp.Mass() * 1e9
    except Exception as e:
        x = None
    e2 = G.expected_volume(p2.get(g) or {}); e3 = G.expected_volume(p3[g])
    nm = p3[g].get('name')
    sv = byname.get(nm) or []
    body = None
    try:
        rep = [r for r in p.Representation.Representations if r.RepresentationIdentifier == 'Body']
        body = [it.is_a() for r in rep for it in r.Items][:3]
        prof = []
        for r in rep:
            for it in r.Items:
                it2 = it.MappingSource.MappedRepresentation.Items[0] if it.is_a('IfcMappedItem') else it
                while it2.is_a('IfcBooleanResult'):
                    it2 = it2.FirstOperand
                if it2.is_a('IfcSweptAreaSolid'):
                    pa = it2.SweptArea
                    prof.append([pa.is_a(), pa.OuterCurve.is_a() if hasattr(pa, 'OuterCurve') else None,
                                 [sg.ParentCurve.is_a() for sg in pa.OuterCurve.Segments][:8] if hasattr(pa, 'OuterCurve') and pa.OuterCurve.is_a('IfcCompositeCurve') else None,
                                 str(pa.OuterCurve)[:300] if hasattr(pa, 'OuterCurve') else None])
    except Exception as e:
        prof = [str(e)[:100]]
    out.append({'gid': g, 'cls': p.is_a(), 'name': nm, 'pt': p3[g].get('pt'), 'qx': p3[g].get('qx'), 'e_v2': e2, 'e_v3': e3,
                'exact': round(x, 1) if x else None, 'v3_over_exact': round(e3 / x, 4) if (x and e3) else None,
                'step_same_name': [round(v, 1) for v in sv[:4]], 'step_over_v3': [round(v / e3, 4) for v in sv[:4]] if e3 else None,
                'body': body, 'prof': prof[:2]})
res = {'id': o['id'], 'step_parts_key': sp, 'n_diff': len(diff),
       'v3_vs_exact_outside_1pct': sum(1 for r in out if r['v3_over_exact'] and abs(r['v3_over_exact'] - 1) > 0.01),
       'rows': sorted(out, key=lambda r: -abs((r['v3_over_exact'] or 1) - 1)), 'sec': round(time.time() - T0, 1)}
json.dump(res, open(outp, 'w'), indent=0, default=str)
print(json.dumps({k: res[k] for k in ('id', 'n_diff', 'v3_vs_exact_outside_1pct', 'sec')}))
