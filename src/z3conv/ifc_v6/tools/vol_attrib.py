#!/usr/bin/env python3
"""Attribute every part outside the grader's 5% volume band to converter or grader.
usage: vol_attrib.py WORKDIR [WORKDIR...]  (a run_case work dir: unz/in IFC, src_parts.jsonl.gz, step_parts.jsonl.gz)
per outside part: expected (census an|q), exact kernel B-rep volume (no tessellation), STEP solid volume ->
  cause = converter (STEP vs exact > 1%) | grader_expectation (exact vs expected > 5%) | both | tessellation (1-5%)"""
import sys, os, json, gzip, glob, collections
import ifcopenshell, ifcopenshell.geom
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
CURVED = ('Circle', 'CircleHollow')
out_all = []
for wd in sys.argv[1:]:
    ifc = next((os.path.join(wd, n) for n in ('excl.ifc', 'hdr.ifc', 'merged.ifc', 'schema.ifc', 'unz.ifc', 'unz.ifcXML', 'in.bin') if os.path.exists(os.path.join(wd, n))), None)
    sp, tp = os.path.join(wd, 'src_parts.jsonl.gz'), os.path.join(wd, 'step_parts.jsonl.gz')
    if not (ifc and os.path.exists(sp) and os.path.exists(tp)):
        continue
    src = [json.loads(l) for l in gzip.open(sp, 'rt')]
    stp = {}
    for l in gzip.open(tp, 'rt'):
        p = json.loads(l)
        if p.get('pid'):
            stp.setdefault(p['pid'], p)
    outside = []
    for p in src:
        s = stp.get(p.get('gid'))
        e = p.get('an') or p.get('q')
        if not s or not e or e <= 0 or not s.get('solids') or not s.get('volume'):
            continue
        r = s['volume'] / e
        if abs(r - 1) > 0.05:
            outside.append((p, s, r))
    if not outside:
        continue
    f = ifcopenshell.open(ifc)
    st = ifcopenshell.geom.settings(); st.set('use-world-coords', True)
    st.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
    for p, s, r in outside:
        e = f.by_guid(p['gid'])
        exact = None
        try:
            sh = ifcopenshell.geom.create_shape(st, e)
            brep = sh.geometry.brep_data if hasattr(sh.geometry, 'brep_data') else sh.brep_data
            fn = '/tmp/_va_%d.brep' % os.getpid()
            open(fn, 'w').write(brep)
            shape = TopoDS_Shape(); breptools.Read(shape, fn, BRep_Builder())
            gp = GProp_GProps(); brepgprop.VolumeProperties(shape, gp); exact = gp.Mass() * 1e9
        except Exception as ex:
            exact = None
        exp = p.get('an') or p.get('q')
        conv_err = (s['volume'] / exact - 1) if exact else None
        grad_err = (exact / exp - 1) if exact else None
        if exact is None:
            cause = 'unknown'
        elif abs(conv_err) > 0.05 and abs(grad_err) > 0.05:
            cause = 'both'
        elif abs(conv_err) > 0.05:
            cause = 'converter'
        elif abs(grad_err) > 0.05:
            cause = 'grader_expectation'
        else:
            cause = 'tessellation_plus_expectation'
        nopen = len(getattr(e, 'HasOpenings', None) or [])
        items = [it for rr in e.Representation.Representations for it in rr.Items if rr.RepresentationIdentifier in (None, 'Body', 'Facetation')]
        kinds = []
        for it in items:
            x = it.MappingSource.MappedRepresentation.Items[0] if it.is_a('IfcMappedItem') else it
            kinds.append(x.is_a() + (':' + x.SweptArea.is_a() if x.is_a('IfcExtrudedAreaSolid') else ''))
        rec = {'case': os.path.basename(wd.rstrip('/')), 'gid': p['gid'], 'cls': p['cls'], 'name': p.get('name'), 'pt': p.get('pt'),
               'expected_kind': 'analytic' if p.get('an') else p.get('qk'), 'expected': round(exp, 1), 'exact': round(exact, 1) if exact else None,
               'step': s['volume'], 'step_over_expected': round(r, 4), 'step_over_exact': round(1 + conv_err, 4) if exact else None,
               'exact_over_expected': round(1 + grad_err, 4) if exact else None, 'cause': cause, 'openings': nopen, 'items': kinds,
               'curved_profile': p.get('pt') in CURVED}
        out_all.append(rec)
        print(json.dumps(rec), flush=True)
c = collections.Counter((r['cause'], r['curved_profile']) for r in out_all)
print(json.dumps({'summary': {f'{k[0]}{"_curved" if k[1] else ""}': v for k, v in c.items()}, 'parts': len(out_all)}))
