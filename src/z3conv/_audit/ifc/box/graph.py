#!/usr/bin/env python3
"""graph.py IN.ifc OUT.json [NVOL] - ifcopenshell census of one IFC model for the IFC audit (read-only).

Per IfcProduct (same body selection as ifc2step6 / ifc_census: Body > Facetation > unnamed; openings, spaces, grids,
annotations, virtual elements skipped): geometry kinds of the body items (through mapped items and boolean operands),
whether ifc2step6 6.0.1 would TRANSCODE it (all items faceted) and whether it has openings (IfcRelVoidsElement).
Products that are transcoded AND voided by openings are written uncut by ifc2step5 / ifc2step6 6.0.1 (no HasOpenings
check). With NVOL > 0, up to NVOL such products get kernel volumes with and without the opening subtraction."""
import sys, json, time, collections, random, math
import ifcopenshell

path, outp = sys.argv[1], sys.argv[2]
NVOL = int(sys.argv[3]) if len(sys.argv) > 3 else 0
T0 = time.time()
out = {'ifcopenshell': ifcopenshell.version}
f = ifcopenshell.open(path)
out['schema'] = f.schema
out['parse_sec'] = round(time.time() - T0, 1)

SKIP = {'IfcOpeningElement', 'IfcOpeningStandardCase', 'IfcSpace', 'IfcGrid', 'IfcAnnotation', 'IfcVirtualElement'}
FACETED = {'IfcFacetedBrep': 'faceted_brep', 'IfcFacetedBrepWithVoids': 'faceted_brep_with_voids',
           'IfcShellBasedSurfaceModel': 'shell_based_surface_model', 'IfcFaceBasedSurfaceModel': 'face_based_surface_model',
           'IfcPolygonalFaceSet': 'polygonal_face_set', 'IfcTriangulatedFaceSet': 'triangulated_face_set'}
KIND = {'IfcExtrudedAreaSolid': 'extrusion', 'IfcExtrudedAreaSolidTapered': 'extrusion_tapered',
        'IfcRevolvedAreaSolid': 'revolved', 'IfcRevolvedAreaSolidTapered': 'revolved',
        'IfcSweptDiskSolid': 'swept_disk', 'IfcSweptDiskSolidPolygonal': 'swept_disk',
        'IfcSurfaceCurveSweptAreaSolid': 'swept_along_curve', 'IfcFixedReferenceSweptAreaSolid': 'swept_along_curve',
        'IfcDirectrixCurveSweptAreaSolid': 'swept_along_curve',
        'IfcAdvancedBrep': 'advanced_brep', 'IfcAdvancedBrepWithVoids': 'advanced_brep',
        'IfcCsgSolid': 'csg', 'IfcBlock': 'csg', 'IfcRightCircularCylinder': 'csg', 'IfcRightCircularCone': 'csg',
        'IfcSphere': 'csg', 'IfcRectangularPyramid': 'csg',
        'IfcHalfSpaceSolid': 'halfspace', 'IfcBoxedHalfSpace': 'halfspace', 'IfcPolygonalBoundedHalfSpace': 'halfspace',
        'IfcBoundingBox': 'bounding_box', 'IfcTriangulatedIrregularNetwork': 'tin',
        'IfcGeometricCurveSet': 'curves', 'IfcGeometricSet': 'curves', 'IfcPolyline': 'curves', 'IfcCompositeCurve': 'curves',
        'IfcTrimmedCurve': 'curves', 'IfcIndexedPolyCurve': 'curves', 'IfcCircle': 'curves', 'IfcLine': 'curves',
        'IfcSectionedSpine': 'sectioned', 'IfcSectionedSolidHorizontal': 'sectioned',
        'IfcTextLiteral': 'text', 'IfcTextLiteralWithExtent': 'text', 'IfcAnnotationFillArea': 'curves'}
CURVED_PROF = {'IfcCircleProfileDef', 'IfcCircleHollowProfileDef', 'IfcEllipseProfileDef'}
_cache = {}


def item_info(it, depth=0):
    """-> (kinds frozenset, transcodable bool)"""
    k = it.id()
    r = _cache.get(k)
    if r is not None:
        return r
    t = it.is_a()
    kinds = set(); tc = True
    if t in FACETED:
        kinds.add(FACETED[t])
    elif t == 'IfcMappedItem':
        kinds.add('mapped_item')
        tgt = it.MappingTarget
        if tgt is not None and tgt.is_a('IfcCartesianTransformationOperator3DnonUniform'):
            kinds.add('mapped_nonuniform_scale')
        elif tgt is not None and (getattr(tgt, 'Scale', None) not in (None, 1.0)):
            kinds.add('mapped_scaled')
        if depth > 8:
            tc = False
        else:
            for si in it.MappingSource.MappedRepresentation.Items or []:
                kk, tt = item_info(si, depth + 1)
                kinds |= kk; tc = tc and tt
    elif t in ('IfcBooleanResult', 'IfcBooleanClippingResult'):
        kinds.add('boolean_clipping' if t == 'IfcBooleanClippingResult' else 'boolean_result')
        tc = False
        fo = it.FirstOperand
        if fo is not None and depth <= 8 and hasattr(fo, 'is_a'):
            kk, _ = item_info(fo, depth + 1)
            kinds |= {('operand:' + x) if not x.startswith('operand:') else x for x in kk if x not in ('boolean_clipping', 'boolean_result')}
    else:
        kinds.add(KIND.get(t, 'other:' + t)); tc = False
        if t in ('IfcExtrudedAreaSolid', 'IfcExtrudedAreaSolidTapered', 'IfcRevolvedAreaSolid'):
            sa = getattr(it, 'SweptArea', None)
            if sa is not None:
                kinds.add('profile:' + sa.is_a())
    r = (frozenset(kinds), tc)
    _cache[k] = r
    return r


def body_items(pr):
    rep = getattr(pr, 'Representation', None)
    if rep is None:
        return None, None, []
    by = {}; ids = []
    for r in rep.Representations or []:
        rid = r.RepresentationIdentifier
        ids.append(str(rid))
        if rid in (None, 'Body', 'Facetation'):
            by.setdefault(rid, []).append(r)
    for rid in ('Body', 'Facetation', None):
        if rid in by:
            items = [it for r in by[rid] for it in (r.Items or [])]
            if items:
                return items, rid, ids
    return None, None, ids


C = collections.Counter
prod_total = 0; with_body = 0; no_rep = C(); no_body_ids = C(); no_body_cls = C()
kind_products = C(); kind_sig = C(); cls_body = C()
n_tc = 0; n_kernel = 0; n_open = 0; n_tc_open = 0; open_on_tc = 0; tc_open_cls = C(); kernel_open = 0
affected = []
mixed_tc = 0
for pr in f.by_type('IfcProduct'):
    prod_total += 1
    t = pr.is_a()
    if t in SKIP:
        continue
    items, rid, ids = body_items(pr)
    if not items:
        if getattr(pr, 'Representation', None) is None:
            no_rep[t] += 1
        else:
            no_body_ids[','.join(sorted(set(ids)))] += 1; no_body_cls[t] += 1
        continue
    with_body += 1; cls_body[t] += 1
    kinds = set(); tc = True
    for it in items:
        kk, tt = item_info(it)
        kinds |= kk; tc = tc and tt
    for k_ in kinds:
        kind_products[k_] += 1
    kind_sig['+'.join(sorted(x for x in kinds if not x.startswith('profile:')))] += 1
    ops = getattr(pr, 'HasOpenings', None) or []
    no = len(ops)
    if tc:
        n_tc += 1
    else:
        n_kernel += 1
    if no:
        n_open += 1
        if tc:
            n_tc_open += 1; open_on_tc += no; tc_open_cls[t] += 1
            if len(affected) < 20000:
                affected.append((pr.GlobalId, t, pr.Name, no, pr.id()))
        else:
            kernel_open += 1
out.update(products_total=prod_total, with_body=with_body, no_representation=dict(no_rep.most_common(30)),
           rep_without_body_by_identifiers=dict(no_body_ids.most_common(20)), rep_without_body_by_class=dict(no_body_cls.most_common(20)),
           body_by_class=dict(cls_body.most_common(30)), kind_products=dict(kind_products.most_common(80)),
           kind_signatures=dict(kind_sig.most_common(25)), transcodable=n_tc, kernel=n_kernel, with_openings=n_open,
           transcodable_with_openings=n_tc_open, openings_on_transcodable=open_on_tc, kernel_with_openings=kernel_open,
           transcodable_with_openings_by_class=dict(tc_open_cls.most_common(20)),
           affected_examples=[list(a[:4]) for a in affected[:15]])
for nm in ('IfcOpeningElement', 'IfcRelVoidsElement', 'IfcRelFillsElement', 'IfcApplication'):
    try:
        out['n_' + nm] = len(f.by_type(nm))
    except Exception:
        out['n_' + nm] = None
try:
    out['applications'] = sorted({'%s %s' % (a.ApplicationFullName, a.Version) for a in f.by_type('IfcApplication')})[:6]
except Exception:
    pass
out['graph_sec'] = round(time.time() - T0, 1)


def mesh_measure(sh):
    g = sh.geometry
    V = g.verts; F = g.faces
    vol = 0.0; area = 0.0; edges = C()
    for i in range(0, len(F), 3):
        a, b, c = F[i], F[i + 1], F[i + 2]
        ax, ay, az = V[3 * a], V[3 * a + 1], V[3 * a + 2]
        bx, by_, bz = V[3 * b], V[3 * b + 1], V[3 * b + 2]
        cx, cy, cz = V[3 * c], V[3 * c + 1], V[3 * c + 2]
        vol += (ax * (by_ * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by_ * cx)) / 6.0
        ux, uy, uz = bx - ax, by_ - ay, bz - az; vx, vy, vz = cx - ax, cy - ay, cz - az
        area += 0.5 * math.sqrt((uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2 + (ux * vy - uy * vx) ** 2)
        for e in ((a, b), (b, c), (c, a)):
            edges[(min(e), max(e))] += 1
    closed = bool(edges) and all(n == 2 for n in edges.values())
    return abs(vol) * 1e9, area * 1e6, closed, len(F) // 3    # mm3, mm2 (kernel output is in metres)


if NVOL > 0 and affected:
    import ifcopenshell.geom
    s_cut = ifcopenshell.geom.settings(); s_unc = ifcopenshell.geom.settings()
    s_unc.set('disable-opening-subtractions', True)
    rnd = random.Random(0)
    samp = rnd.sample(affected, min(NVOL, len(affected)))
    res = []
    for gid, t, name, no, eid in samp:
        rec = {'gid': gid, 'cls': t, 'name': name, 'openings': no}
        try:
            pr = f.by_id(eid)
            t1 = time.time()
            a = mesh_measure(ifcopenshell.geom.create_shape(s_cut, pr))
            b = mesh_measure(ifcopenshell.geom.create_shape(s_unc, pr))
            rec.update(cut_vol=round(a[0], 1), cut_area=round(a[1], 1), cut_closed=a[2], uncut_vol=round(b[0], 1),
                       uncut_area=round(b[1], 1), uncut_closed=b[2], tris=(a[3], b[3]), sec=round(time.time() - t1, 2))
        except Exception as e:
            rec['error'] = '%s: %s' % (type(e).__name__, str(e)[:160])
        res.append(rec)
        if time.time() - T0 > 2400:
            rec['note'] = 'time budget reached'
            break
    out['vol_samples'] = res
out['sec'] = round(time.time() - T0, 1)
json.dump(out, open(outp, 'w'), default=str)
