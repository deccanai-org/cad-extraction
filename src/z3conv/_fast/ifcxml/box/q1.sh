#!/bin/bash
cd /work/agentwork/ifcxml/find
/opt/conv/env/bin/python - <<'PY'
import json, gzip, collections
sn = {}
for l in gzip.open('sniff.jsonl.gz', 'rt'):
    r = json.loads(l); sn[r['sha256']] = r
paths = collections.defaultdict(list)
for ds in ('d3', 'd4'):
    for l in gzip.open(f'xml_rows_{ds}.jsonl.gz', 'rt'):
        e = json.loads(l)
        if len(paths[e['sha256']]) < 3: paths[e['sha256']].append(ds + ' ' + e['path'][-150:])
u = '975259beed76943f28749874b64f3019bc00c3fd82e0cc6a87487fcb5b059c74'
print('UNRESOLVED', json.dumps(sn.get(u))[:400], paths.get(u))
d3 = [r for r in sn.values() if 'd3' in r['ds']]
print('d3 distinct', len(d3), collections.Counter(r.get('kind') for r in d3))
print('d3 zip contents:')
for r in d3:
    if r.get('kind', '').startswith('zip') or r.get('kind') in ('gzip_xml', 'not_xml'):
        print('  ', r['sha256'][:12], r['size'], r.get('kind'), [(m['name'][-50:], m.get('kind'), m.get('root')) for m in (r.get('members') or [])][:4], paths[r['sha256']][:1])
print('xml rows whose path mentions ifc (any dataset), by root:')
c = collections.Counter(); ex = {}
for s, ps in paths.items():
    if any('ifc' in p.lower() for p in ps):
        r = sn.get(s, {}); k = (r.get('kind'), r.get('root'), 'd3' if 'd3' in r.get('ds', []) else 'd4')
        c[k] += 1; ex.setdefault(k, (s[:12], r.get('size'), ps[0]))
for k, n in c.most_common(40): print('  ', n, k, ex[k])
print('ifcxml candidates:')
for r in sn.values():
    if r.get('kind') in ('ifcxml', 'ifcxml_in_zip'):
        print('  ', r['sha256'][:12], r['size'], r['kind'], r.get('root'), r.get('schema'), r.get('cfg'), r.get('member'), r.get('member_size'), r['ds'], r.get('n_rows'), paths[r['sha256']][:2])
PY
