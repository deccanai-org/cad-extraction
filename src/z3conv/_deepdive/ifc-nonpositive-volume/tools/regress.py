#!/usr/bin/env python3
"""regress.py [BASE:]TAG CASE_DIR... : per-root regression check of occ_<TAG>.jsonl against the original read-back
(occ_roots.jsonl). A root is 'worse' if it gains a non-positive or invalid solid or loses all its solids;
'better' if it loses them; volume of untouched-good roots must be unchanged."""
import json, sys, collections
tag = sys.argv[1]
base = 'roots'
if ':' in tag:
    base, tag = tag.split(':')                 # BASE:NEW e.g. wA:wB (both occ_<tag>.jsonl)
tot = collections.Counter()
for d in sys.argv[2:]:
    A = [json.loads(l) for l in open(d + '/occ_%s.jsonl' % base)]; B = [json.loads(l) for l in open(d + '/occ_%s.jsonl' % tag)]
    c = collections.Counter(); worse = []
    if all(x.get('key') for x in A + B) and len(set(x['key'] for x in A)) == len(A):
        bk = {x['key']: x for x in B}               # stable product key (GlobalId) when both runs have it
        pairs = [(a, bk.get(a['key'], {'solids': []})) for a in A]
    else:
        pairs = list(zip(A, B))
    for a, b in pairs:
        sa = a.get('solids', []); sb = b.get('solids', [])
        ba = sum(1 for s in sa if not (s[0] and s[0] > 0) or not s[2]); bb = sum(1 for s in sb if not (s[0] and s[0] > 0) or not s[2])
        c['roots'] += 1
        if sa and not sb:
            c['lost_all_solids'] += 1; worse.append(a['i'])
        elif bb > ba:
            c['worse'] += 1; worse.append(a['i'])
        elif bb < ba:
            c['better'] += 1
        if ba and not bb:
            c['fully_fixed'] += 1
        if ba == 0:
            va = sum(s[0] for s in sa); vb = sum(s[0] for s in sb)
            c['good_roots'] += 1
            c['good_roots_vol_changed'] += abs(vb - va) > 5e-3 * max(abs(va), 1)
    print(d, dict(c), 'worse roots:', worse[:10])
    tot.update(c)
print('TOTAL', dict(tot))
