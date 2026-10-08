"""fieldscan.py : old-engine bolt strings MM<d>*<L>/f1/.../f10 of the audit dumps: distribution of f4 / f7 / f9 for slotted (f1 or f2 != 0)
vs round groups, per model -> candidates for Tekla's 'slotted holes in parts' selection."""
import json, gzip, glob, collections, os
R = {}; tot = collections.defaultdict(collections.Counter)
for p in glob.glob('wk/k/*/dump.json.gz'):
    d = json.load(gzip.open(p, 'rt'))
    if d.get('path') != 'old': continue
    seen = set(); c = collections.defaultdict(collections.Counter)
    for b in d['bolts']:
        if b['g'] in seen: continue
        seen.add(b['g']); f = (b.get('prof') or '').split('/')
        if len(f) != 11: c['layout'][len(f)] += 1; continue
        try: sl = float(f[1]) != 0 or float(f[2]) != 0
        except ValueError: continue
        k = 'slot' if sl else 'round'
        for i in (4, 7, 9):
            c[f'{k}_f{i}'][f[i]] += 1; tot[f'{k}_f{i}'][f[i]] += 1
    R[p.split('/')[2]] = {k: dict(v.most_common(8)) for k, v in c.items()}
json.dump({'total': {k: dict(v.most_common(12)) for k, v in tot.items()}, 'models': R}, open('fieldscan.json', 'w'), indent=1)
print(json.dumps({k: dict(v.most_common(10)) for k, v in tot.items()}))
print(json.dumps(R.get('5a2284473e4e')))
