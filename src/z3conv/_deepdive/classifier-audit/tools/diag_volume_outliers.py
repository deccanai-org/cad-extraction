#!/usr/bin/env python3
"""For the join's worst volume outliers of a model: source product -> profile type + parameters, openings (IfcRelVoidsElement),
predicted ratio from the fillets the census area formula ignores. usage: diag_volume_outliers.py SRC.ifc RESULT.json"""
import sys, json, math
import ifcopenshell

f = ifcopenshell.open(sys.argv[1])
res = json.load(open(sys.argv[2]))
worst = res['join']['volume']['worst']


def body_item(p):
    for r in p.Representation.Representations:
        if r.RepresentationIdentifier in (None, 'Body', 'Facetation'):
            it = r.Items[0]
            if it.is_a('IfcMappedItem'):
                it = it.MappingSource.MappedRepresentation.Items[0]
            return it
    return None


def fillet_ratio(pr):
    t = pr.is_a(); g = lambda n: getattr(pr, n, None) or 0.0
    if t == 'IfcRectangleHollowProfileDef':
        X, Y, w, ro, ri = g('XDim'), g('YDim'), g('WallThickness'), g('OuterFilletRadius'), g('InnerFilletRadius')
        a0 = X * Y - (X - 2 * w) * (Y - 2 * w)
        return (a0 - (4 - math.pi) * (ro * ro - ri * ri)) / a0, dict(X=X, Y=Y, w=w, ro=ro, ri=ri)
    if t == 'IfcLShapeProfileDef':
        h, b, th, fr, er = g('Depth'), g('Width') or g('Depth'), g('Thickness'), g('FilletRadius'), g('EdgeRadius')
        a0 = th * (h + b - th) + (1 - math.pi / 4) * fr * fr
        return (a0 - 2 * (1 - math.pi / 4) * er * er) / a0, dict(h=h, b=b, t=th, fr=fr, er=er)
    if t == 'IfcUShapeProfileDef':
        h, b, tw, tf, fr, er = g('Depth'), g('FlangeWidth'), g('WebThickness'), g('FlangeThickness'), g('FilletRadius'), g('EdgeRadius')
        a0 = 2 * b * tf + (h - 2 * tf) * tw
        return (a0 + 2 * (1 - math.pi / 4) * fr * fr - 2 * (1 - math.pi / 4) * er * er) / a0, dict(h=h, b=b, tw=tw, tf=tf, fr=fr, er=er, slope=g('FlangeSlope'))
    if t == 'IfcIShapeProfileDef':
        return 1.0, {k: g(k) for k in ('OverallWidth', 'OverallDepth', 'WebThickness', 'FlangeThickness', 'FilletRadius')}
    return None, None


for w in worst:
    ratio, gid, cls, name, kind = w
    try:
        p = f.by_guid(gid)
    except Exception:
        print('gid not found', gid); continue
    it = body_item(p)
    ops = len(p.HasOpenings or []) if hasattr(p, 'HasOpenings') else 0
    pr = it.SweptArea if it is not None and it.is_a('IfcExtrudedAreaSolid') else None
    fr, params = fillet_ratio(pr) if pr is not None else (None, None)
    print(json.dumps({'ratio_step_vs_census': ratio, 'cls': cls, 'name': name, 'item': it.is_a() if it else None,
                      'profile': pr.is_a() if pr is not None else None, 'profile_name': getattr(pr, 'ProfileName', None),
                      'openings': ops, 'fillet_corrected_ratio_pred': round(fr, 4) if fr else None, 'params': params}))
