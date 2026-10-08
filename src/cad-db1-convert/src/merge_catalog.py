"""Merge harvested IFC profile defs -> name: most common VALID (kind, dims|pts) over Tekla-authored IFCs."""
import json, gzip, glob, collections, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db1step import _valid
by = collections.defaultdict(collections.Counter); files = 0
for f in glob.glob('catalog/parts/*.jsonl.gz'):
    for line in gzip.open(f, 'rt'):
        r = json.loads(line); files += 1
        if 'error' in r or 'Tekla Structures' not in r['app']: continue
        for p in r['profiles']:
            v = p.get('dims') if 'dims' in p else p.get('pts')
            if not _valid(p['kind'], v): continue
            by[p['name']][json.dumps({k: p[k] for k in ('kind', 'dims', 'pts') if k in p}, sort_keys=True)] += 1
cat = {}
for name, c in by.items():
    (best, n), = c.most_common(1); e = json.loads(best); e['n'] = n; e['variants'] = len(c); cat[name] = e
json.dump(cat, open('catalog/tekla_profiles.json', 'w'))
print('names', len(cat), collections.Counter(e['kind'] for e in cat.values()).most_common())
