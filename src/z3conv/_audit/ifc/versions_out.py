#!/usr/bin/env python3
"""matrix.json + evidence.json -> versions list for the structured audit (printed as JSON)."""
import json, os, collections
D = os.path.dirname(os.path.abspath(__file__))
m = json.load(open(os.path.join(D, 'matrix.json')))


def status(e):
    g = e['class1'] + e['class2'] + e['class3']
    if g == 0:
        return 'not_yet_run'
    if e['class3'] == g:
        return 'failing'
    if e['class1'] == g and e['ungraded'] == 0:
        return 'converts_ok'
    return 'partial'


def entry(prefix, k, e, note=''):
    return {'version': f'{prefix}{k}', 'status': status(e), 'distinct': e['distinct'], 'class1': e['class1'], 'class2': e['class2'],
            'class3': e['class3'], 'notes': (f"ungraded/pending {e['ungraded']}; " if e['ungraded'] else '') + 'top: ' + '; '.join(e['top_reasons'][:3]) + (('. ' + note) if note else '')}


out = []
for sec, prefix in (('by_declared_schema', 'schema '), ('by_container', 'container '), ('by_authoring_version', 'tool '),
                    ('by_size_band', 'size '), ('by_geometry_kind', 'geometry ')):
    for k, e in m[sec].items():
        out.append(entry(prefix, k, e))
print(json.dumps(out, indent=1))
