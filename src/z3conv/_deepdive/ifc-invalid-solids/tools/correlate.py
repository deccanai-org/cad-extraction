#!/usr/bin/env python3
"""Join diag_step (OCC BRepCheck per invalid solid) with mesh_audit (kernel-free mesh defects per FACETED_BREP) by root
SDR id; tabulate OCC status signature x mesh defect signature.  usage: correlate.py PREFIX... (reads d_PREFIX.json, m_PREFIX.jsonl)"""
import sys, json, collections


def mesh_sig(m):
    s = []
    if m['edge_use'].get('1'): s.append('open')
    if m['edge_use'].get('3'): s.append('nonmanifold')
    if m['orient_conflicts']: s.append('orient_conflict')
    if m['components'] > 1: s.append('multi_comp')
    if m['neg_components']: s.append('neg_comp')
    if m['nested_pairs']: s.append('nested')
    elif m['overlap_pairs']: s.append('overlap')
    return '+'.join(s) or 'clean'


tab = collections.Counter(); base = collections.Counter(); ex = {}
for p in sys.argv[1:]:
    d = json.load(open(f'd_{p}.json'))
    ms = {}
    for l in open(f'm_{p}.jsonl'):
        m = json.loads(l); ms.setdefault(m['sdr'], []).append(m)
        if m.get('pd') != m['sdr']:
            ms.setdefault(m.get('pd'), []).append(m)
    bad_roots = collections.defaultdict(list)
    for b in d['invalid']:
        bad_roots[b['eid']].append(b)
    for sdr, mm in ms.items():
        if not mm or mm[0].get('pd') != sdr:
            continue
        sig = '|'.join(sorted(mesh_sig(m) for m in mm))
        base[(sig, sdr in bad_roots)] += 1
    for eid, bs in bad_roots.items():
        occ = '+'.join(sorted(set(k for b in bs for k in b['status'])))
        mm = ms.get(eid, [])
        sig = '|'.join(sorted(mesh_sig(m) for m in mm)) or 'no_brep'
        tab[(occ, sig)] += 1
        ex.setdefault((occ, sig), (p, bs[0]['name'], bs[0]['root'], bs[0].get('brep')))
print('invalid roots: OCC status signature x mesh signature')
for k, n in tab.most_common():
    print(f'{n:5d}  {k[0]:70s}  {k[1]:40s}  e.g. {ex[k]}')
print('\nall roots: mesh signature -> (#roots with an invalid solid, #roots all valid)')
sigs = sorted(set(k[0] for k in base), key=lambda s: -(base[(s, True)] + base[(s, False)]))
for s in sigs:
    print(f'{s:60s} invalid={base[(s, True)]:5d} valid={base[(s, False)]:6d}')
