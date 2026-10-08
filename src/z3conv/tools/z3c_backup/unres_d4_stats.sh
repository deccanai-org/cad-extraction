#!/bin/bash
/opt/conv/env/bin/python - <<'PY'
import json, collections, os
d = json.load(open('/opt/pkgd4r3/unresolved_all.json'))
ext = collections.Counter(); byt = collections.Counter(); shas = set(); how = collections.Counter(); proj = collections.Counter(); keys = collections.Counter()
d1 = set(json.load(open('/opt/z3c/z4_disk12_duplicates.json'))) if os.path.exists('/opt/z3c/z4_disk12_duplicates.json') else set()
for pid, us in d.items():
    if not pid.startswith('Zentitude-data-4'): continue
    for u in us:
        e = os.path.splitext(u['path'].split(' :: ')[-1])[1].lower() or '(none)'
        ext[e] += 1; byt[e] += u.get('bytes') or 0; shas.add(u['sha256']); how[u.get('why') or u.get('reason') or u.get('src_how')] += 1
        proj[pid] += 1; keys[(u.get('raw_key') or '')[:12]] += 1
print('RESULT files', sum(ext.values()), 'distinct sha', len(shas), 'GB', round(sum(byt.values())/1e9, 1), 'projects', len(proj))
print('RESULT ext', [(e, n, round(byt[e]/1e9, 2)) for e, n in ext.most_common(15)])
print('RESULT raw_key prefix', keys.most_common(5)); print('RESULT top projects', [(p[18:90], n) for p, n in proj.most_common(6)])
print('RESULT fields', sorted(next(iter(next(iter(d.values()))[0:1])).keys()))
PY
