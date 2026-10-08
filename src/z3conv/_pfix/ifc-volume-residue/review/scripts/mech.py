#!/usr/bin/env python3
"""mech.py CONV.py IFC TARGETS.json MODEL_ID OUT.json
Reviewer mechanism check for patch 1 (opening contact walls): for the products that dev3 wrote as valid solids but
dev3+patch lost / wrote as open-surface, build the product with the ifcopenshell kernel (OCC B-rep, openings applied)
on the ORIGINAL file and again after the patch's own in-memory repair_opening_shells(); also the opening bodies those
products use (valid closed solid? volume) and whether any repaired shell is shared with a non-opening product."""
import sys, os, json, time, importlib.util, collections
T0 = time.time()
conv, ifc, tgt, mid, outp = sys.argv[1:6]
spec = importlib.util.spec_from_file_location('v6', conv)
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
import ifcopenshell, ifcopenshell.geom
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL

T = json.load(open(tgt))[mid]
targets = list(dict.fromkeys(T['lost'] + T['deg'] + T.get('deg_strict', [])))
f = ifcopenshell.open(ifc)
FN = '/tmp/_mech_%d.brep' % os.getpid()


def cnt(x, k):
    e = TopExp_Explorer(x, k); n = 0
    while e.More():
        n += 1; e.Next()
    return n


def shape(e):
    print('shape', e.id(), e.is_a(), getattr(e, 'Name', None), round(time.time() - T0, 1), file=sys.stderr, flush=True)
    s = ifcopenshell.geom.settings(); s.set('use-world-coords', True); s.set('iterator-output', WR.SERIALIZED)
    t = time.time()
    try:
        sh = ifcopenshell.geom.create_shape(s, e)
    except Exception as ex:
        return {'ok': False, 'err': str(ex)[:120], 'sec': round(time.time() - t, 1)}
    d = sh.geometry.brep_data
    (open(FN, 'wb') if isinstance(d, bytes) else open(FN, 'w')).write(d)
    x = TopoDS_Shape(); breptools.Read(x, FN, BRep_Builder())
    g = GProp_GProps(); brepgprop.VolumeProperties(x, g)
    return {'ok': True, 'solids': cnt(x, TopAbs_SOLID), 'shells': cnt(x, TopAbs_SHELL), 'faces': cnt(x, TopAbs_FACE),
            'vol': round(g.Mass() * 1e9, 1), 'valid': bool(BRepCheck_Analyzer(x).IsValid()), 'sec': round(time.time() - t, 1)}


def poly(e):
    """the converter's own kernel settings (polyhedron with holes) - does the product produce any face?"""
    s, _, _ = v6.kernel_settings('poly')
    try:
        sh = ifcopenshell.geom.create_shape(s, e)
        g = sh.geometry
        return {'ok': True, 'verts': len(g.verts) // 3, 'faces': len(g.faces) // 3}
    except Exception as ex:
        return {'ok': False, 'err': str(ex)[:120]}


prods = [f.by_guid(g) for g in targets]
prods = [p for p in prods if p is not None]
ops = {}
for p in prods:
    for rel in p.HasOpenings or []:
        ops[rel.RelatedOpeningElement.id()] = rel.RelatedOpeningElement

# which shells the patch touches (spy), and their sharing
rep = {}
orig = v6.contact_wall_pairs


def spy(sh):
    r = orig(sh)
    if r[0]:
        rep[sh.id()] = {'faces': len(sh.CfsFaces or []), 'pairs': len(r[0]), 'bad0': r[1], 'bad1': r[2]}
    return r


v6.contact_wall_pairs = spy


def users(ent, lim=4000):
    out = set(); todo = [ent]; seen = set(); n = 0
    while todo and n < lim:
        e = todo.pop(); n += 1
        for inv in f.get_inverse(e):
            if inv.id() in seen:
                continue
            seen.add(inv.id())
            if inv.is_a('IfcProduct'):
                out.add(inv.is_a())
            else:
                todo.append(inv)
    return sorted(out)


op_shells = {}
for oid, o in ops.items():
    items, _ = v6.body_items(o)
    op_shells[oid] = [sh.id() for it in (items or []) for sh in v6._opening_shells(it) if sh is not None]

before_p = {p.GlobalId: {'name': p.Name, 'brep': shape(p), 'poly': poly(p)} for p in prods}
before_o = {oid: shape(o) for oid, o in ops.items()}
all_with_ops = [p for p in f.by_type('IfcProduct') if getattr(p, 'HasOpenings', None)]
stats = v6.repair_opening_shells(all_with_ops)
after_p = {p.GlobalId: {'brep': shape(p), 'poly': poly(p)} for p in prods}
after_o = {oid: shape(o) for oid, o in ops.items()}
rows = []
for p in prods:
    g = p.GlobalId
    my_ops = [rel.RelatedOpeningElement.id() for rel in p.HasOpenings or []]
    touched = [oid for oid in my_ops if any(s in rep and rep[s]['bad1'] < rep[s]['bad0'] for s in op_shells.get(oid, []))]
    rows.append({'gid': g, 'name': before_p[g]['name'], 'kind': 'lost' if g in T['lost'] else 'degraded',
                 'before': before_p[g], 'after': after_p[g], 'openings': len(my_ops), 'openings_repaired': len(touched),
                 'repaired_ops': [{'op': oid, 'shells': [dict(rep[s], id=s) for s in op_shells[oid] if s in rep],
                                   'before': before_o[oid], 'after': after_o[oid]} for oid in touched][:6]})
shared = {}
for s in rep:
    shared[s] = users(f.by_id(s))
res = {'id': mid, 'conv': conv, 'repair_stats': stats, 'targets': len(prods),
       'repaired_shells': len(rep), 'repaired_shells_applied': sum(1 for r in rep.values() if r['bad1'] < r['bad0']),
       'repaired_shells_nonmanifold_after': sum(1 for r in rep.values() if r['bad1'] < r['bad0'] and r['bad1'] > 0),
       'shells_shared_with_non_opening_products': {str(k): v for k, v in shared.items() if any(c != 'IfcOpeningElement' for c in v)},
       'summary': {
           'before_valid_solid': sum(1 for r in rows if r['before']['brep'].get('ok') and r['before']['brep'].get('valid') and r['before']['brep'].get('solids')),
           'after_valid_solid': sum(1 for r in rows if r['after']['brep'].get('ok') and r['after']['brep'].get('valid') and r['after']['brep'].get('solids')),
           'after_no_faces_poly': sum(1 for r in rows if not r['after']['poly'].get('ok') or not r['after']['poly'].get('faces')),
           'before_no_faces_poly': sum(1 for r in rows if not r['before']['poly'].get('ok') or not r['before']['poly'].get('faces')),
           'repaired_openings_valid_before': sum(1 for r in rows for o in r['repaired_ops'] if o['before'].get('valid')),
           'repaired_openings_valid_after': sum(1 for r in rows for o in r['repaired_ops'] if o['after'].get('valid')),
           'repaired_openings_total': sum(len(r['repaired_ops']) for r in rows)},
       'rows': rows, 'sec': round(time.time() - T0, 1)}
json.dump(res, open(outp, 'w'), indent=0, default=str)
print(json.dumps({k: res[k] for k in ('id', 'conv', 'repair_stats', 'targets', 'repaired_shells', 'repaired_shells_applied',
                                      'repaired_shells_nonmanifold_after', 'shells_shared_with_non_opening_products', 'summary', 'sec')}, default=str))
