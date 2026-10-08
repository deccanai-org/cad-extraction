#!/usr/bin/env python3
"""join occ_roots.jsonl with lumps2.jsonl per case dir: npv solids / invalid solids by FACETED_BREP lump kind"""
import json, sys, collections
for d in sys.argv[1:]:
    L = collections.defaultdict(list)
    for l in open(d + '/lumps2.jsonl'):
        x = json.loads(l); L[x['pd']].append(x)
    by = collections.Counter(); byinv = collections.Counter(); roots = collections.Counter(); rootnpv = collections.Counter()
    names = collections.Counter()
    for l in open(d + '/occ_roots.jsonl'):
        x = json.loads(l)
        if x.get('empty'): continue
        ks = sorted(set(b['kind'] for b in L.get(x['pd'], []))) or ['no_brep']
        k = '+'.join(ks)
        roots[k] += 1
        npv = sum(1 for v, ns, ok in x['solids'] if not (v is not None and v > 0))
        inv = sum(1 for v, ns, ok in x['solids'] if not ok)
        by[k] += npv; byinv[k] += inv; rootnpv[k] += npv > 0
        if npv:
            nm = (L.get(x['pd']) or [{}])[0].get('name') or ''
            names[nm.split('-')[0] if '-' in nm else 'member/other'] += 1
    print(d, 'roots by kind', dict(roots))
    print('   npv solids by kind', dict(by), ' roots with npv', dict(rootnpv))
    print('   invalid solids by kind', dict(byinv))
    print('   npv roots by name prefix', dict(names.most_common(8)))
