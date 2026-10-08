#!/usr/bin/env python3
"""IFC audit: join the live index, the result harvest and the source scan -> version matrix + flaw evidence.
Inputs (local copies): live/index_0032.jsonl.gz, box_out/harvest.jsonl.gz, box_out/scan.jsonl.gz. Output: matrix.json, evidence.json."""
import json, gzip, re, collections, statistics, os, sys
D = os.path.dirname(os.path.abspath(__file__))
C = collections.Counter
idx = {json.loads(l)['id']: json.loads(l) for l in gzip.open(os.path.join(D, 'live/index_0032.jsonl.gz'), 'rt')}
idx = {k: v for k, v in idx.items() if v.get('pipeline') == 'ifc'}
scan = {}
sp = os.path.join(D, 'box_out/scan.jsonl.gz')
if os.path.exists(sp):
    for l in gzip.open(sp, 'rt'):
        r = json.loads(l); scan[r['id']] = r
harv = collections.defaultdict(list)
for l in gzip.open(os.path.join(D, 'box_out/harvest.jsonl.gz'), 'rt'):
    h = json.loads(l)
    mid = (h.get('id') or '').replace('ifc-', '', 1)
    harv[mid].append(h)


def reasons(r):
    if r['class'] == 3:
        return [x.split(' (')[0] for x in r['reasons']]
    if r['class'] == 2:
        out = [x.split(':')[0] for x in r['issues']] + [s['type'] for s in r['standins']]
        return [re.sub(r'_[\d.]+$', '', x) for x in out]
    return []


def app_family(s):
    """(family, version) from header originating system / IfcApplication strings"""
    t = ' '.join(x for x in s if x)
    tl = t.lower()
    m = re.search(r'sds/?2[^0-9v]*v?\s*(\d{4}\.\d+|\d+\.\d+)', tl)
    if 'sds/2' in tl or 'sds2' in tl:
        v = m.group(1) if m else '?'
        grp = ('v' + v.split('.')[0]) if v[:2] == '20' else ('7.x' if v.startswith('7') else ('6.x' if v.startswith('6') else v))
        return 'SDS/2', grp
    if 'tekla' in tl:
        m = re.search(r'tekla structures\s*(\d{4}i?|\d{2}\.\d)', tl)
        return 'Tekla Structures', m.group(1) if m else '?'
    if 'revit' in tl or 'exporter' in tl and ('x64' in tl or 'alternate ui' in tl or 'default ui' in tl):
        m = re.search(r'revit[^0-9]*(\d{4})', tl)
        if m:
            return 'Revit', m.group(1)
        m = re.search(r'exporter\s*(\d+)\.', tl)
        if m:
            n = int(m.group(1)); return 'Revit', str(2000 + n) if n < 30 else '?'
        return 'Revit', '?'
    for k, nm in (('solidworks', 'SolidWorks'), ('advance steel', 'Advance Steel'), ('autocad', 'AutoCAD'), ('plant 3d', 'AutoCAD Plant 3D'),
                  ('prostructures', 'Bentley ProStructures'), ('aecosim', 'Bentley AECOsim'), ('openbuildings', 'Bentley OpenBuildings'),
                  ('microstation', 'Bentley MicroStation'), ('allplan', 'Allplan'), ('archicad', 'ArchiCAD'), ('navisworks', 'Navisworks'),
                  ('idea statica', 'IDEA StatiCa'), ('strucad', 'StruCAD'), ('strumis', 'Strumis'), ('ifcopenshell', 'IfcOpenShell'),
                  ('inventor', 'Inventor'), ('rhino', 'Rhino'), ('sketchup', 'SketchUp'), ('vectorworks', 'Vectorworks'), ('dds-cad', 'DDS-CAD'),
                  ('magicad', 'MagiCAD'), ('bocad', 'bocad'), ('prosteel', 'ProSteel'), ('scia', 'SCIA'), ('robot', 'Robot'), ('etabs', 'ETABS'),
                  ('ram ', 'RAM'), ('staad', 'STAAD'), ('trimble', 'Trimble'), ('catia', 'CATIA'), ('nx ', 'Siemens NX')):
        if k in tl:
            m = re.search(r'(\d{4})', t)
            return nm, m.group(1) if m else '?'
    return ('other: ' + t[:40]) if t.strip() else 'unknown', '?'


def band(n):
    n = n or 0
    for lim, nm in ((1e6, '<1MB'), (10e6, '1-10MB'), (50e6, '10-50MB'), (100e6, '50-100MB'), (250e6, '100-250MB'), (500e6, '250-500MB')):
        if n < lim:
            return nm
    return '>=500MB'


GEO = {'faceted_brep': 'faceted B-rep', 'faceted_brep_with_voids': 'faceted B-rep with voids', 'shell_based_surface_model': 'shell-based surface model',
       'face_based_surface_model': 'face-based surface model', 'polygonal_face_set': 'polygonal face set', 'triangulated_face_set': 'triangulated face set',
       'extrusion': 'extrusion', 'extrusion_tapered': 'extrusion', 'boolean_clipping': 'boolean (clipping)', 'boolean_result': 'boolean (result)',
       'swept_disk': 'swept disk', 'revolved': 'revolved', 'swept_along_curve': 'swept along curve', 'advanced_brep': 'advanced B-rep',
       'csg': 'CSG primitive', 'halfspace': 'half-space', 'bounding_box': 'bounding box stand-in', 'mapped_item': 'mapped item',
       'mapped_nonuniform_scale': 'mapped item (non-uniform scale)', 'mapped_scaled': 'mapped item (scaled)', 'curves': 'curves only', 'tin': 'TIN'}


def geo_kinds(g):
    ks = set()
    for k, n in (g.get('kind_products') or {}).items():
        if not n:
            continue
        k2 = k.replace('operand:', '')
        if k2.startswith('profile:'):
            if k2 in ('profile:IfcCircleProfileDef', 'profile:IfcCircleHollowProfileDef', 'profile:IfcEllipseProfileDef'):
                ks.add('curved profile (circle / ellipse)')
            continue
        if k2.startswith('other:'):
            ks.add('other: ' + k2[6:]); continue
        ks.add(GEO.get(k2, k2))
    if (g.get('n_IfcOpeningElement') or 0) > 0:
        ks.add('openings (IfcRelVoidsElement)')
    if (g.get('transcodable_with_openings') or 0) > 0:
        ks.add('faceted body + openings (transcoded uncut by v5 / v6.0.1)')
    return ks


rows = []
for mid, r in idx.items():
    s = scan.get(mid) or {}
    h = s.get('hdr') or {}
    g = s.get('graph') or {}
    apps = [h.get('fn_originating'), h.get('fn_preprocessor')] + list(g.get('applications') or [])
    fam, ver = app_family([h.get('fn_originating')] + list(g.get('applications') or []) + [h.get('fn_preprocessor')]) if s else ('not scanned', '?')
    decl = h.get('schema') or ('ALL-ZERO BYTES' if s and s.get('bytes') and s.get('nul_bytes') == s.get('bytes') else (r.get('schema') or 'unknown'))
    cont = 'ifcZIP' if '.ifczip' in r['paths'][0].lower() else ('zip named .ifc' if s.get('zip') else ('gzip' if s.get('gzip') else 'plain SPF'))
    if s.get('xml'):
        cont = 'ifcXML'
    rows.append({'id': mid, 'class': r['class'], 'status': r['status'], 'reasons': reasons(r), 'schema_declared': decl, 'container': cont,
                 'family': fam, 'version': ver, 'band': band(r['size']), 'geo': geo_kinds(g) if g else set(),
                 'code': r.get('converter_code') or ('reused-v5' if r['reused'] else None), 'reused': r['reused'], 'scan': bool(s)})


def agg(key, multi=False):
    d = {}
    for x in rows:
        ks = x[key] if multi else [x[key]]
        for k in ks:
            e = d.setdefault(k, {'distinct': 0, 'class1': 0, 'class2': 0, 'class3': 0, 'ungraded': 0, '_r': C()})
            e['distinct'] += 1
            if x['class'] in (1, 2, 3):
                e['class%d' % x['class']] += 1
                for y in set(x['reasons']):
                    e['_r'][f"{x['class']}:{y}"] += 1
            else:
                e['ungraded'] += 1
    out = {}
    for k, e in sorted(d.items(), key=lambda kv: -kv[1]['distinct']):
        e['top_reasons'] = [f'{a} ({n})' for a, n in e.pop('_r').most_common(4)]
        out[k] = e
    return out


matrix = {'by_declared_schema': agg('schema_declared'), 'by_container': agg('container'),
          'by_authoring_family': agg('family'),
          'by_authoring_version': {}, 'by_size_band': agg('band'), 'by_geometry_kind': agg('geo', multi=True)}
for x in rows:
    x['fv'] = f"{x['family']} {x['version']}"
matrix['by_authoring_version'] = agg('fv')
matrix['by_converter'] = agg('code')
json.dump(matrix, open(os.path.join(D, 'matrix.json'), 'w'), indent=1, default=list)

# ---------------- evidence
ev = {}
ev['scan'] = {'models': len(scan), 'errors': sum(1 for s in scan.values() if s.get('error')),
              'graph_ok': sum(1 for s in scan.values() if s.get('graph')), 'graph_errors': sum(1 for s in scan.values() if s.get('graph_errors') and not s.get('graph'))}
# openings flaw
op = C(); op_parts = C(); samples = C(); s_by = C(); c1_uncut = set(); c1_atrisk = set(); eff = []
for mid, s in scan.items():
    g = s.get('graph') or {}
    r = idx.get(mid)
    if not r or not g:
        continue
    code = r.get('converter_code') or ('reused-v5' if r['reused'] else 'none')
    n = g.get('transcodable_with_openings') or 0
    if n:
        op[(r['class'], code)] += 1; op_parts[(r['class'], code)] += n
        if r['class'] == 1:
            c1_atrisk.add(mid)
    for v in g.get('vol_samples') or []:
        vd = v.get('verdict')
        samples[(r['class'], code, vd)] += 1
        s_by[vd] += 1
        if vd == 'step_uncut':
            eff.append(v.get('opening_effect'))
            if r['class'] == 1:
                c1_uncut.add(mid)
ev['openings'] = {'models_with_transcoded_openings_by_class_code': {f'{k[0]}|{k[1]}': v for k, v in sorted(op.items(), key=str)},
                  'parts_by_class_code': {f'{k[0]}|{k[1]}': v for k, v in sorted(op_parts.items(), key=str)},
                  'class1_models_at_risk': len(c1_atrisk), 'class1_models_with_confirmed_uncut_part': len(c1_uncut),
                  'class1_confirmed_examples': sorted(c1_uncut)[:15],
                  'sample_verdicts': dict(s_by), 'sample_verdicts_by_class_code': {f'{k[0]}|{k[1]}|{k[2]}': v for k, v in sorted(samples.items(), key=str)},
                  'uncut_opening_effect_quantiles': (lambda xs: {'n': len(xs), 'median': statistics.median(xs), 'p90': xs[int(.9 * (len(xs) - 1))], 'max': xs[-1]} if xs else None)(sorted(x for x in eff if x is not None))}
# body representations the converter and the census both skip
nb = C(); nbm = 0; nbcls = C()
for s in scan.values():
    g = s.get('graph') or {}
    t = sum((g.get('rep_without_body_by_identifiers') or {}).values())
    if t:
        nbm += 1
        for k, v in (g.get('rep_without_body_by_identifiers') or {}).items():
            nb[k] += v
        for k, v in (g.get('rep_without_body_by_class') or {}).items():
            nbcls[k] += v
ev['rep_without_body'] = {'models': nbm, 'products_by_identifiers': dict(nb.most_common(15)), 'products_by_class': dict(nbcls.most_common(15))}
# zip with several IFC members
zm = [(mid, s['zip']) for mid, s in scan.items() if s.get('zip')]
ev['zip'] = {'containers': len(zm), 'multi_ifc': [[mid[:16], z.get('ifc_members'), z.get('ifc_member_bytes')[:5], (idx.get(mid) or {}).get('class')] for mid, z in zm if (z.get('ifc_members') or 0) > 1],
             'non_ifc_member_chosen': [[mid[:16], z.get('chosen')] for mid, z in zm if z.get('chosen') and not z['chosen'].lower().endswith(('.ifc', '.ifcxml'))]}
ev['spf_blocks_gt1'] = [[mid[:16], s.get('spf_blocks'), (idx.get(mid) or {}).get('class')] for mid, s in scan.items() if (s.get('spf_blocks') or 0) > 1]
ev['not_terminated'] = [[mid[:16], s.get('bytes'), (idx.get(mid) or {}).get('class')] for mid, s in scan.items() if s.get('terminated') is False]
ev['all_zero'] = [[mid[:16], s.get('bytes'), s.get('nul_bytes'), s.get('first_non_nul')] for mid, s in scan.items() if s.get('bytes') and s.get('nul_bytes', 0) >= 0.5 * s['bytes']]
ev['xml'] = [mid[:16] for mid, s in scan.items() if s.get('xml')]
# voids-with-breps and curved geometry in class-1 v5 STEPs
vw = C(); cv = C()
for mid, s in scan.items():
    g = s.get('graph') or {}; r = idx.get(mid)
    if not r or not g:
        continue
    code = r.get('converter_code') or ('reused-v5' if r['reused'] else 'none')
    kp = g.get('kind_products') or {}
    if kp.get('faceted_brep_with_voids'):
        vw[(r['class'], code)] += 1
    if any(kp.get(k) for k in ('swept_disk', 'revolved', 'advanced_brep', 'operand:swept_disk', 'operand:revolved')) or \
            any(kp.get(k) for k in kp if 'Circle' in k or 'Ellipse' in k):
        cv[(r['class'], code)] += 1
ev['faceted_brep_with_voids_models'] = {f'{k[0]}|{k[1]}': v for k, v in sorted(vw.items(), key=str)}
ev['curved_geometry_models'] = {f'{k[0]}|{k[1]}': v for k, v in sorted(cv.items(), key=str)}
ev['mapped_nonuniform_models'] = sum(1 for s in scan.values() if ((s.get('graph') or {}).get('kind_products') or {}).get('mapped_nonuniform_scale'))
json.dump(ev, open(os.path.join(D, 'evidence.json'), 'w'), indent=1, default=list)
print(json.dumps(ev, indent=1, default=list)[:6000])
