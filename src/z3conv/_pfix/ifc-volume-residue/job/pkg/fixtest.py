#!/usr/bin/env python3
"""fixtest.py IFC [--all] - products with openings whose kernel result is empty: opening shells analysed (non-manifold
edges, coincident opposite face pairs = contact walls), contact walls removed in memory, kernel re-run.
--all: every product with openings (volume with openings vs without, before / after the repair)"""
import sys, os, importlib.util, collections, json, time
import numpy as np
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ifc2step6_dev3.py'))
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
v6.np = np
f = ifcopenshell.open(sys.argv[1])
ALL = '--all' in sys.argv
def meshvol(V, faces):
    t = 0.0
    for fc in faces:
        lp = fc[0]
        for i in range(1, len(lp) - 1):
            t += np.dot(V[lp[0]], np.cross(V[lp[i]], V[lp[i + 1]])) / 6.0
    return t
def kvol(e, noop=False):
    s, _, m = v6.kernel_settings('tri')
    if noop:
        s.set('disable-opening-subtractions', True)
    try:
        sh = ifcopenshell.geom.create_shape(s, e)
        V, faces, iids = v6.kernel_geometry(sh.geometry, m)
        return (meshvol(V, faces) if len(faces) else 0.0), len(faces)
    except Exception as ex:
        return None, str(ex)[:80]
def faceted_shells(item, depth=0):
    if item.is_a('IfcMappedItem'):
        for si in item.MappingSource.MappedRepresentation.Items:
            yield from faceted_shells(si, depth + 1)
    elif item.is_a('IfcFacetedBrep'):
        yield item.Outer
    elif item.is_a('IfcBooleanResult'):
        yield from faceted_shells(item.FirstOperand, depth + 1)
        if item.SecondOperand.is_a('IfcFacetedBrep'):
            yield item.SecondOperand.Outer
def analyse(sh):
    loops = []
    for fc in sh.CfsFaces:
        bs = fc.Bounds
        lp = [p.id() for p in bs[0].Bound.Polygon] if len(bs) == 1 else None
        if lp is not None and not bs[0].Orientation:
            lp = lp[::-1]
        loops.append(lp)
    ec = collections.Counter()
    for fc in sh.CfsFaces:
        for b in fc.Bounds:
            ids = [p.id() for p in b.Bound.Polygon]
            for i in range(len(ids)):
                ec[tuple(sorted((ids[i], ids[(i + 1) % len(ids)])))] += 1
    nm = sum(1 for n in ec.values() if n != 2)
    # contact walls: two single-loop faces over the same point set with opposite cyclic order
    key = collections.defaultdict(list)
    for k, lp in enumerate(loops):
        if lp:
            key[frozenset(lp)].append(k)
    pairs = []
    for ks in key.values():
        if len(ks) == 2:
            a, b = loops[ks[0]], loops[ks[1]]
            i = b.index(a[0])
            rb = b[i::-1] + b[:i:-1]
            if rb == a:
                pairs.append(tuple(ks))
    return nm, pairs
SKIP = v6.SKIP_TYPES
prods = [p for p in f.by_type('IfcProduct') if p.is_a() not in SKIP and getattr(p, 'HasOpenings', None)]
print('products with openings', len(prods))
t0 = time.time()
res = collections.Counter(); out = []
for p in prods:
    v1, n1 = kvol(p)
    if not ALL and v1 not in (None, 0.0) and n1:
        continue
    v0, n0 = kvol(p, True)
    rec = {'gid': p.GlobalId, 'cls': p.is_a(), 'name': p.Name, 'vol_open': None if v1 is None else round(v1, 1), 'vol_noopen': None if v0 is None else round(v0, 1), 'openings': []}
    for o in p.HasOpenings:
        op = o.RelatedOpeningElement
        items, _ = v6.body_items(op)
        for it in items or []:
            for sh in faceted_shells(it):
                nm, pairs = analyse(sh)
                rec['openings'].append({'shell': sh.id(), 'faces': len(sh.CfsFaces), 'nonmanifold_edges': nm, 'contact_pairs': len(pairs)})
    out.append((p, rec))
print('scanned', len(prods), 'in %.0fs' % (time.time() - t0), 'selected', len(out))
# in-memory repair: drop contact-wall pairs of every opening shell
fixed = set(); nfix = 0
for p in prods:
    for o in p.HasOpenings:
        items, _ = v6.body_items(o.RelatedOpeningElement)
        for it in items or []:
            for sh in faceted_shells(it):
                if sh.id() in fixed:
                    continue
                fixed.add(sh.id())
                nm, pairs = analyse(sh)
                if pairs:
                    drop = {k for pr in pairs for k in pr}
                    sh.CfsFaces = [fc for k, fc in enumerate(sh.CfsFaces) if k not in drop]
                    nfix += 1
print('opening shells repaired', nfix)
for p, rec in out:
    v2, n2 = kvol(p)
    rec['vol_open_after'] = None if v2 is None else round(v2, 1)
    rec['faces_after'] = n2
    r = 'empty->ok' if (not rec['vol_open'] and v2) else ('still_empty' if not v2 else 'ok')
    if rec['vol_open'] and v2 and abs(v2 - rec['vol_open']) > 1e-6 * max(1, abs(v2)):
        r = 'changed'
    res[r] += 1
    print(json.dumps({k: rec[k] for k in ("gid", "name", "vol_open", "vol_noopen", "vol_open_after", "faces_after")}))
print('RESULT', dict(res))
