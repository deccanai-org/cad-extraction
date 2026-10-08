#!/usr/bin/env python3
"""graph2.py IN.ifc OUT.json - class-1 correctness checks the grader cannot see (read-only).
  multi_body : products with items in more than one of the Body / Facetation / unnamed representations
               (ifc2step5 summed them -> the part is written twice; ifc2step6 takes Body only)
  brep_voids : products whose body holds IfcFacetedBrepWithVoids (ifc2step5 wrote the voids as extra positive solids)
For up to 6 products of each kind: kernel volume of each representation (mm3) and of the product as a whole."""
import sys, json, time, collections, math, random
import ifcopenshell, ifcopenshell.geom

path, outp = sys.argv[1], sys.argv[2]
T0 = time.time()
f = ifcopenshell.open(path)
SKIP = {'IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcSpace', 'IfcGrid', 'IfcAnnotation', 'IfcVirtualElement'}
out = {'schema': f.schema}
multi = []; bvoid = []
_mc = {}


def has_voids(it, d=0):
    k = it.id()
    if k in _mc:
        return _mc[k]
    t = it.is_a(); r = False
    if t == 'IfcFacetedBrepWithVoids':
        r = True
    elif t == 'IfcMappedItem' and d < 8:
        r = any(has_voids(x, d + 1) for x in it.MappingSource.MappedRepresentation.Items or [])
    _mc[k] = r
    return r


n = 0
for pr in f.by_type('IfcProduct'):
    if pr.is_a() in SKIP or pr.Representation is None:
        continue
    reps = [r for r in pr.Representation.Representations or [] if r.RepresentationIdentifier in (None, 'Body', 'Facetation') and r.Items]
    if not reps:
        continue
    n += 1
    ids = [str(r.RepresentationIdentifier) for r in reps]
    if len(reps) > 1:
        multi.append((pr.id(), pr.GlobalId, pr.is_a(), pr.Name, ids))
    body = [r for r in reps if r.RepresentationIdentifier == 'Body'] or [r for r in reps if r.RepresentationIdentifier == 'Facetation'] or reps
    if any(has_voids(it) for r in body for it in r.Items):
        bvoid.append((pr.id(), pr.GlobalId, pr.is_a(), pr.Name, ids))
out.update(products_with_body=n, multi_body=len(multi), multi_body_ids=collections.Counter(','.join(x[4]) for x in multi).most_common(5),
           multi_body_examples=[list(x[1:]) for x in multi[:6]], brep_voids=len(bvoid), brep_voids_examples=[list(x[1:]) for x in bvoid[:6]])


def vol(sh):
    V = sh.geometry.verts; F = sh.geometry.faces; v = 0.0
    for i in range(0, len(F), 3):
        a, b, c = F[i], F[i + 1], F[i + 2]
        ax, ay, az = V[3 * a:3 * a + 3]; bx, by_, bz = V[3 * b:3 * b + 3]; cx, cy, cz = V[3 * c:3 * c + 3]
        v += (ax * (by_ * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by_ * cx)) / 6.0
    return abs(v) * 1e9


s = ifcopenshell.geom.settings()
rnd = random.Random(0)
for key, lst in (('multi_body_samples', multi), ('brep_voids_samples', bvoid)):
    res = []
    for eid, gid, t, name, ids in rnd.sample(lst, min(6, len(lst))):
        pr = f.by_id(eid); rec = {'gid': gid, 'cls': t, 'name': name, 'reps': ids}
        try:
            rec['product_volume'] = round(vol(ifcopenshell.geom.create_shape(s, pr)), 1)
        except Exception as e:
            rec['product_error'] = str(e)[:120]
        per = {}
        for r in pr.Representation.Representations or []:
            if r.RepresentationIdentifier in (None, 'Body', 'Facetation') and r.Items:
                try:
                    per[str(r.RepresentationIdentifier)] = round(vol(ifcopenshell.geom.create_shape(s, pr, r)), 1)
                except Exception as e:
                    per[str(r.RepresentationIdentifier)] = 'error: ' + str(e)[:80]
        rec['rep_volumes'] = per
        if key == 'brep_voids_samples':
            # outer shell volume alone vs with voids: a writer that turns voids into solids reports outer + voids
            try:
                tot_void = 0.0; outer = 0.0
                import numpy as np
                def shell_vol(sh, M=None):
                    v = 0.0
                    for fc in sh.CfsFaces:
                        lp = fc.Bounds[0].Bound.Polygon
                        P = [p.Coordinates for p in lp]
                        for i in range(1, len(P) - 1):
                            a, b, c = P[0], P[i], P[i + 1]
                            v += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
                    return abs(v)
                import ifcopenshell.util.unit as uu
                sc = float(uu.calculate_unit_scale(f)) * 1000.0
                stack = [it for r in pr.Representation.Representations if r.RepresentationIdentifier in (None, 'Body', 'Facetation') for it in r.Items]
                while stack:
                    it = stack.pop()
                    if it.is_a('IfcMappedItem'):
                        stack.extend(it.MappingSource.MappedRepresentation.Items or [])
                    elif it.is_a('IfcFacetedBrepWithVoids'):
                        outer += shell_vol(it.Outer) * sc ** 3
                        tot_void += sum(shell_vol(v) for v in it.Voids) * sc ** 3
                rec['outer_shell_mm3'] = round(outer, 1); rec['voids_mm3'] = round(tot_void, 1)
            except Exception as e:
                rec['shell_error'] = str(e)[:120]
        res.append(rec)
        if time.time() - T0 > 900:
            break
    out[key] = res
out['sec'] = round(time.time() - T0, 1)
json.dump(out, open(outp, 'w'), default=str)
