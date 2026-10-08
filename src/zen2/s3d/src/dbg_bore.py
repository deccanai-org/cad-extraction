import json, glob, collections, os
from common import *
D = os.path.join(WORK, 'done', 'piping'); c = collections.Counter(); ex = []
for f in sorted(glob.glob(D + '/pb*.json')):
    for r in json.load(open(f))['results']:
        if 'error' in r or not r['checks']['bore_mismatch']: continue
        J = read_json(os.path.join(OUT, r['json'])); comp = {x['oid']: x for x in J['components']}
        for s in J['checks']['bore_mismatch_samples']:
            c[tuple(sorted(s['types']))] += 1
            if len(ex) < 6:
                ex.append((J['name'], s['bores'], [(comp[p]['pcf_type'], comp[p]['part_class'], [(q['index'], q['bore_mm'], q.get('size_source')) for q in comp[p]['ports'] if q['conn'] == s['conn']]) for p in comp if any(q['conn'] == s['conn'] for q in comp[p]['ports'])]))
print(c.most_common(12))
for e in ex: print(json.dumps(e)[:400])
