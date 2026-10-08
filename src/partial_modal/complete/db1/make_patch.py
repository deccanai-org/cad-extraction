"""restoration_log.json colour verdicts -> db1 patch.json (accept for GREY-verified flagged parts, AMBER marks). Deterministic."""
import json, pathlib
H = pathlib.Path(__file__).resolve().parent
for short, tag in (('n1', 'n1_db1_small'), ('n2', 'n2_db1_addon')):
    L = json.loads((H / 'out' / short / 'restoration_log.json').read_text())
    ops = []
    for pid, v in sorted(L['colour_by_part'].items()):
        why = '; '.join(dict.fromkeys(v.get('reasons') or []))[:1500]
        if v['colour'] in ('GREY', 'GREEN'):
            ops.append({'op': 'accept', 'id': f'db1:verdict:{pid}', 'part_id': pid,
                        'provenance': {'what': 'reviewed against the DB1 record: ' + why, 'source': 'DB1 (restoration_log.json colour_by_part)'}})
        elif v['colour'] == 'AMBER':
            ops.append({'op': 'set_fields', 'id': f'db1:amber:{pid}', 'part_id': pid, 'fields': {}, 'colour': 'AMBER',
                        'resolves': [],
                        'provenance': {'what': why, 'source': 'DB1 record (restoration_log.json)', 'basis': why}})
    if short == 'n2':                   # Hilti HAS-M anchors: catalogue item, nut / washer proportions nominal -> AMBER
        import glob
        iss = json.load(open(glob.glob(str(H.parents[1] / 'testB_results' / short / 'scripts' / '*' / 'schedules' / 'issues.json'))[0]))
        for pid, v in sorted((iss.get('parts') or {}).items()):
            cats = sorted({f['category'] for f in v.get('flags', [])})
            if 'bolt_nominal_head_nut' in cats:
                ops.append({'op': 'set_fields', 'id': f'db1:anchor:{pid}', 'part_id': pid, 'fields': {}, 'colour': 'AMBER',
                            'resolves': [{'part_id': pid, 'category': c} for c in cats],
                            'provenance': {'what': 'HILTI HAS-M 3/4 in adhesive anchor (DB1 bolt standard HILTI_HASM): rod diameter, length and position exact from the DB1 bolt record; nut and washer drawn with nominal heavy-hex proportions (1.6d across flats, 0.8d nut height)',
                                           'source': 'DB1 bolt group record (skipped_records.json standard HILTI_HASM)',
                                           'basis': 'Hilti publishes no nut / washer dimensions in the DB1 and HAS-M is a catalogue product, not an ASTM table item: nut and washer proportions are ESTIMATED as nominal heavy hex (A563-like)'}})
    out = {'schema': 'pmp-completion-patch/1', 'track': 'db1', 'tag': tag, 'model_id': L.get('model_id', ''),
           'generated_by': 'complete/db1/make_patch.py', 'generated_at': '2026-10-08T00:00:00Z', 'inputs': {}, 'ops': ops, 'notes': []}
    (H / 'out' / short / 'patch.json').write_text(json.dumps(out, sort_keys=True))
    print(short, {k: sum(o['op'] == k for o in ops) for k in ('accept', 'set_fields')})
