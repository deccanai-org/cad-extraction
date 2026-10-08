#!/usr/bin/env python3
"""recov.py WD_DEV3 WD_COMB OUT.json - every part whose STEP differs between dev3 and dev3+patches (gid join of step_parts):
lost / new / volume changed. For each new or changed part an INDEPENDENT expectation: exact OCC B-rep of the product without
openings (X0) minus OCC common(product, fused opening bodies after the patch's in-memory repair) -> E; compare with the
STEP read-back volume S (patched) and report validity / tags / level from step_parts + sidecar."""
import sys, os, json, gzip, importlib.util, collections, time
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
T0 = time.time()
wa, wb, outp = sys.argv[1:4]
CONV = '/work/agentwork/ifc-volume-residue-review/pkg/conv_comb/ifc2step6.py'
spec = importlib.util.spec_from_file_location('v6', CONV)
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)


def load(p):
    out = {}
    try:
        for l in gzip.open(p, 'rt'):
            r = json.loads(l)
            if r.get('pid'):
                out.setdefault(r['pid'], r)
    except Exception:
        pass
    return out


A, Bp = load(os.path.join(wa, 'step_parts.jsonl.gz')), load(os.path.join(wb, 'step_parts.jsonl.gz'))
side = {}
try:
    for p in json.load(open(os.path.join(wb, 'out.step.parts.json')))['parts']:
        side.setdefault(p.get('gid'), p)
except Exception:
    pass
lost = [g for g in A if g not in Bp]
new = [g for g in Bp if g not in A]
chg = [g for g in Bp if g in A and not (abs((A[g].get('volume') or 0) - (Bp[g].get('volume') or 0)) <= 1e-6 * max(abs(A[g].get('volume') or 0), abs(Bp[g].get('volume') or 0), 1.0))]
res = {'wa': wa, 'wb': wb, 'parts_a': len(A), 'parts_b': len(Bp), 'lost': lost[:50], 'n_lost': len(lost), 'n_new': len(new), 'n_changed': len(chg),
       'valid_changed_a': sum(1 for g in A if g in Bp and (A[g].get('valid') or 0) != (Bp[g].get('valid') or 0))}
ifc = os.path.join(wb, 'in.bin')
f = ifcopenshell.open(ifc)
res['null_curve_segments_dropped'] = v6.repair_null_curve_segments(f)      # patch 2, in memory (as the converter)
st = {'n': 0}


def brep(e, noop=False):
    s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
    if noop:
        s.set('disable-opening-subtractions', True)
    sh = ifcopenshell.geom.create_shape(s, e)
    d = sh.geometry.brep_data
    fn = '/tmp/_recov_%d.brep' % os.getpid()
    (open(fn, 'wb') if isinstance(d, bytes) else open(fn, 'w')).write(d)
    x = TopoDS_Shape(); breptools.Read(x, fn, BRep_Builder())
    return x


def vol(x):
    g = GProp_GProps(); brepgprop.VolumeProperties(x, g); return g.Mass() * 1e9


targets = [f.by_guid(g) for g in new + chg]
v6.repair_opening_shells([p for p in targets if p is not None])     # the patch's in-memory repair (openings only)
rows = []
for p in targets:
    if p is None:
        continue
    g = p.GlobalId
    r = {'gid': g, 'cls': p.is_a(), 'name': p.Name, 'kind': 'new' if g in new else 'changed', 'S_a': (A.get(g) or {}).get('volume'),
         'S_b': Bp[g].get('volume'), 'valid_b': Bp[g].get('valid'), 'solids_b': Bp[g].get('solids'), 'desc_b': Bp[g].get('desc'),
         'level': (side.get(g) or {}).get('level'), 'tags': (side.get(g) or {}).get('tags'), 'openings': len(p.HasOpenings or [])}
    try:
        x0 = brep(p, True); X0 = vol(x0)
        ops = []
        for rel in p.HasOpenings or []:
            try:
                ops.append(brep(rel.RelatedOpeningElement))
            except Exception as e:
                r.setdefault('op_fail', 0); r['op_fail'] += 1
        tool = None
        for o in ops:
            tool = o if tool is None else BRepAlgoAPI_Fuse(tool, o).Shape()
        I = vol(BRepAlgoAPI_Common(x0, tool).Shape()) if tool is not None else 0.0
        r['X0'] = round(X0, 1); r['I'] = round(I, 1); r['E'] = round(X0 - I, 1)
        r['S_over_E'] = round(r['S_b'] / (X0 - I), 5) if r['S_b'] and X0 - I > 0 else None
        r['tool_valid'] = all(BRepCheck_Analyzer(o).IsValid() for o in ops)
        bb = Bnd_Box(); brepbndlib.Add(x0, bb); r['bbox_X0'] = [round(v, 1) for v in bb.Get()]
        r['bbox_S'] = Bp[g].get('bbox')
    except Exception as e:
        r['error'] = str(e)[:200]
    rows.append(r)
res['rows'] = rows
res['S_over_E_outside_0.5pct'] = sum(1 for r in rows if r.get('S_over_E') and abs(r['S_over_E'] - 1) > 0.005)
res['invalid_b'] = sum(1 for r in rows if (r.get('valid_b') or 0) < (r.get('solids_b') or 0))
res['sec'] = round(time.time() - T0, 1)
json.dump(res, open(outp, 'w'), indent=0, default=str)
print(json.dumps({k: v for k, v in res.items() if k != 'rows'}, default=str))
