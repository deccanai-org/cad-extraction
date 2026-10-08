"""restoration_log.json + restored_geometry.jsonl -> pmp-completion-patch/1 (GREEN source restorations only). Deterministic."""
import csv, glob, json, pathlib, sys
H = pathlib.Path(__file__).resolve().parent
R = H.parents[1]
TAGS = {'n4_ifc_c2s': 'n4', 'n5_sds2': 'n5'}
for tag, short in TAGS.items():
    d = H / 'out' / tag
    log = json.loads((d / 'restoration_log.json').read_text())
    rows = [json.loads(l) for l in (d / 'restored_geometry.jsonl').read_text().splitlines() if l.strip()]
    parts = list(csv.DictReader(open(glob.glob(str(R / 'testB_results' / short / 'scripts' / '*' / 'schedules' / 'parts.csv'))[0])))
    by_name = {p['name']: p['part_id'] for p in parts}
    ids = {p['part_id'] for p in parts}
    miss = json.loads(open(glob.glob(str(R / 'testB_results' / short / 'scripts' / '*' / 'schedules' / 'missing_parts.json'))[0]).read())
    miss = miss.get('missing', miss) if isinstance(miss, dict) else miss
    ents = {e.get('part_id'): e for e in log.get('entries', [])}
    est = json.loads((R / 'complete' / 'estimate' / 'out' / tag / 'patch.json').read_text())
    est_sup = {}
    for o in est['ops']:
        if o['op'] == 'add_part' and o.get('supersedes'):
            est_sup[(o['part'].get('assembly_mark'), o['part'].get('part_mark'))] = o['supersedes']
    ops = []
    for r in rows:
        e = ents.get(r['part_id'], {})
        prov = {'what': e.get('what') or r['restore'].get('kind'), 'source': r.get('source') or e.get('source', ''),
                'basis': e.get('basis', r['restore'].get('how', '')),
                'evidence': {k: e[k] for k in ('weight', 'steelbuild_exact_part', 'source_fields', 'volume_check') if k in e}}
        geom = {'kind': 'faceted', 'solids': r['solids']}
        if r['part_id'] in ids:
            ops.append({'op': 'replace_part', 'id': f"s2i:{r['part_id']}", 'part_id': r['part_id'], 'geometry': geom,
                        'colour': 'GREEN', 'provenance': prov})
            continue
        rep = [by_name[l] for l in r['restore'].get('replaces', []) if l in by_name]
        if rep:
            ops.append({'op': 'replace_part', 'id': f"s2i:{r['part_id']}", 'part_id': rep[0], 'geometry': geom,
                        'colour': 'GREEN', 'provenance': prov})
            continue
        m, p = 'M' + str(e.get('member', '')), 'P' + str(e.get('piece', ''))
        ops.append({'op': 'add_part', 'id': f"s2i:{r['part_id']}", 'colour': 'GREEN', 'geometry': geom,
                    'part': {'role': 'plate', 'ifc_class': 'IfcPlate', 'name': r.get('label', r['part_id']) + ' bar grating',
                             'designation': e.get('name', ''), 'part_mark': p, 'assembly_mark': m},
                    'provenance': prov, 'supersedes': est_sup.get((m, p), []), 'resolves': []})
    for rm in log.get('removed', []):
        pid = by_name.get(rm['part_label'])
        if pid:
            ops.append({'op': 'remove_part', 'id': f's2i:rm:{pid}', 'part_id': pid, 'colour': 'GREEN',
                        'provenance': {'what': rm['what'], 'source': 'SDS/2 stored BLT pieces: ' + ', '.join(rm['stored_bolt_pieces']),
                                       'basis': rm['basis']}})
    out = {'schema': 'pmp-completion-patch/1', 'track': 'sds2_ifc', 'tag': tag, 'model_id': log['model_id'],
           'generated_by': 'complete/sds2_ifc/make_patch.py', 'generated_at': '2026-10-08T00:00:00Z', 'inputs': {}, 'ops': ops, 'notes': []}
    (d / 'patch.json').write_text(json.dumps(out, sort_keys=True))
    print(tag, {k: sum(o['op'] == k for o in ops) for k in ('replace_part', 'add_part', 'remove_part')},
          'unmapped removed', len(log.get('removed', [])) - sum(o['op'] == 'remove_part' for o in ops),
          'supersedes', [o.get('supersedes') for o in ops if o['op'] == 'add_part'])
