#!/usr/bin/env python3
"""probe.py IFC ID -> one JSON line: what the two converter patches would change in this file (parse only, no geometry).
patch 2: composite curves with ParentCurve-less segments; is the curve still closed without them (endpoint chain)?
patch 1: repair_opening_shells over every product with openings (the patched converter's own functions), per repaired shell
the face count / pairs / non-manifold edges before and after."""
import sys, os, json, re, time, math, collections, importlib.util
T0 = time.time()
path, mid = sys.argv[1], sys.argv[2]
CONV = os.environ.get('CONV_COMB', '/work/agentwork/ifc-volume-residue-review/pkg/conv_comb/ifc2step6.py')
spec = importlib.util.spec_from_file_location('v6comb', CONV)
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
import ifcopenshell
out = {'id': mid, 'size': os.path.getsize(path)}
raw = open(path, 'rb').read()
out['raw_nullseg'] = len(re.findall(rb'IFCCOMPOSITECURVESEGMENT\s*\([^;]*?,\s*(?:\$|#0)\s*\)\s*;', raw, re.I))
hdr = raw[:4000].decode('latin-1', 'replace')
m = re.search(r"FILE_NAME\s*\((.*?)\);", hdr, re.S)
out['hdr'] = m.group(1)[:300] if m else None
del raw
try:
    f = ifcopenshell.open(path)
except Exception as e:
    out['error'] = 'open: %s' % str(e)[:200]; print(json.dumps(out)); sys.exit(0)
out['schema'] = f.schema
try:
    out['apps'] = sorted({(x.ApplicationFullName or '') + ' ' + (x.Version or '') for x in f.by_type('IfcApplication')})[:4]
except Exception:
    out['apps'] = []


def pt2(p):
    c = p.Coordinates
    return (float(c[0]), float(c[1])) if len(c) >= 2 else None


def seg_ends(c, same):
    """(start, end) of a 2D/3D bounded curve in traversal order, or None"""
    try:
        if c.is_a('IfcPolyline'):
            P = [tuple(float(x) for x in q.Coordinates) for q in c.Points]
            s, e = P[0], P[-1]
        elif c.is_a('IfcTrimmedCurve'):
            t1 = [x for x in c.Trim1 if hasattr(x, 'is_a') and x.is_a('IfcCartesianPoint')]
            t2 = [x for x in c.Trim2 if hasattr(x, 'is_a') and x.is_a('IfcCartesianPoint')]
            if not t1 or not t2:
                return None
            s, e = tuple(float(x) for x in t1[0].Coordinates), tuple(float(x) for x in t2[0].Coordinates)
            if not c.SenseAgreement:
                s, e = e, s
        elif c.is_a('IfcIndexedPolyCurve'):
            P = [tuple(float(x) for x in q) for q in c.Points.CoordList]
            if c.Segments:
                i0 = int(c.Segments[0].wrappedValue[0]) - 1; i1 = int(c.Segments[-1].wrappedValue[-1]) - 1
                s, e = P[i0], P[i1]
            else:
                s, e = P[0], P[-1]
        elif c.is_a('IfcCompositeCurve'):
            ch = chain(c.Segments)
            return (ch['start'], ch['end']) if ch and ch.get('start') is not None else None
        else:
            return None
        return (s, e) if same else (e, s)
    except Exception:
        return None


def chain(segs):
    ends = []
    for sg in segs:
        r = seg_ends(sg.ParentCurve, bool(sg.SameSense))
        if r is None:
            return {'evaluable': False}
        ends.append(r)
    if not ends:
        return {'evaluable': False}
    tol = lambda p, q: math.dist(p[:2], q[:2]) <= 1e-6 * (1 + max(abs(x) for x in p[:2] + q[:2]))
    gaps = [i for i in range(len(ends) - 1) if not tol(ends[i][1], ends[i + 1][0])]
    closed = tol(ends[-1][1], ends[0][0])
    return {'evaluable': True, 'gaps': len(gaps), 'closed': closed, 'start': ends[0][0], 'end': ends[-1][1],
            'gap_len': max([math.dist(ends[-1][1][:2], ends[0][0][:2])] + [math.dist(ends[i][1][:2], ends[i + 1][0][:2]) for i in gaps])}


cc_rows = []
for cc in f.by_type('IfcCompositeCurve'):
    try:
        segs = list(cc.Segments or ())
        nul = [sg for sg in segs if sg.ParentCurve is None]
        if not nul:
            continue
        keep = [sg for sg in segs if sg.ParentCurve is not None]
        ch_keep = chain(keep) if keep else {'evaluable': False}
        users = sorted({x.is_a() for x in f.get_inverse(cc)})
        prods = set()
        # products using it: profile -> swept solid -> ... upward (bounded)
        todo = [cc]; seen = set(); n = 0
        while todo and n < 2000:
            e = todo.pop(); n += 1
            for inv in f.get_inverse(e):
                if inv.id() in seen:
                    continue
                seen.add(inv.id())
                if inv.is_a('IfcProduct'):
                    prods.add((inv.is_a(), inv.Name, inv.GlobalId))
                else:
                    todo.append(inv)
        cc_rows.append({'cc': cc.id(), 'segs': len(segs), 'null': len(nul), 'kept': len(keep), 'self_intersect': str(cc.SelfIntersect),
                        'kept_types': [sg.ParentCurve.is_a() for sg in keep][:6],
                        'kept_chain': {k: v for k, v in ch_keep.items() if k not in ('start', 'end')}, 'users': users,
                        'products': sorted(prods)[:6], 'n_products': len(prods)})
    except Exception as e:
        cc_rows.append({'cc': cc.id(), 'error': str(e)[:200]})
out['p2_curves'] = len(cc_rows)
out['p2_open_after'] = sum(1 for r in cc_rows if r.get('kept') and r['kept_chain'].get('evaluable') and not r['kept_chain'].get('closed'))
out['p2_unevaluable'] = sum(1 for r in cc_rows if r.get('kept') and not r['kept_chain'].get('evaluable'))
out['p2_rows'] = cc_rows[:30]

# patch 1
det = []
orig = v6.contact_wall_pairs


def spy(sh):
    r = orig(sh)
    if r[0]:
        det.append({'shell': sh.id(), 'faces': len(sh.CfsFaces or []), 'pairs': len(r[0]), 'bad0': r[1], 'bad1': r[2], 'applied': r[2] < r[1]})
    return r


v6.contact_wall_pairs = spy
prods = [p for p in f.by_type('IfcProduct') if getattr(p, 'HasOpenings', None)]
out['products_with_openings'] = len(prods)
t1 = time.time()
try:
    out['p1'] = v6.repair_opening_shells(prods)
except Exception as e:
    out['p1'] = {'error': str(e)[:200]}
out['p1_sec'] = round(time.time() - t1, 1)
out['p1_shells'] = det[:40]
out['p1_applied'] = sum(1 for d in det if d['applied'])
out['p1_applied_not_manifold_after'] = sum(1 for d in det if d['applied'] and d['bad1'] > 0)
out['p1_pairs_not_applied'] = sum(1 for d in det if not d['applied'])
if det:
    # products whose openings use a repaired shell
    rep = {d['shell'] for d in det if d['applied']}
    hit = []
    for p in prods:
        for rel in p.HasOpenings:
            items, _ = v6.body_items(rel.RelatedOpeningElement)
            if any(sh is not None and sh.id() in rep for it in (items or []) for sh in v6._opening_shells(it)):
                hit.append(p.GlobalId); break
    out['p1_products'] = len(hit); out['p1_products_ex'] = hit[:10]
out['sec'] = round(time.time() - T0, 1)
print(json.dumps(out, default=str))
