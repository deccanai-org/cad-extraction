#!/usr/bin/env python3
"""residual.py CASE_DIR : per-root list of roots that have a non-positive or invalid solid before (out.stp) or after
(split2.stp), with the FACETED_BREP lump structure (lumps2.jsonl)"""
import json, sys, collections
d = sys.argv[1]
A = [json.loads(l) for l in open(d + '/occ_roots.jsonl')]; B = [json.loads(l) for l in open(d + '/occ_roots_split2.jsonl')]
L = {}
for l in open(d + '/lumps2.jsonl'):
    x = json.loads(l); L.setdefault(x['pd'], []).append(x)
agg = collections.Counter()
for a, b in zip(A, B):
    sa = a.get('solids', []); sb = b.get('solids', [])
    npa = sum(1 for s in sa if not (s[0] and s[0] > 0)); npb = sum(1 for s in sb if not (s[0] and s[0] > 0))
    iva = sum(1 for s in sa if not s[2]); ivb = sum(1 for s in sb if not s[2])
    agg['npv_before'] += npa; agg['npv_after'] += npb; agg['inv_before'] += iva; agg['inv_after'] += ivb
    if npa or npb or iva or ivb:
        nm = [(x['name'], x['faces'], x['lumps'], x['kind'], round(sum(Lx['vol'] for Lx in x['lump_detail']), 1)) for x in L.get(a['pd'], [])]
        print(a['i'], nm[:3], 'A n/npv/inv/vol', len(sa), npa, iva, round(sum(s[0] or 0 for s in sa), 1), '| B', len(sb), npb, ivb, round(sum(s[0] or 0 for s in sb), 1))
print(dict(agg))
