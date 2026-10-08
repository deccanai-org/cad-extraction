#!/usr/bin/env python3
"""debug_root.py CASE_DIR ROOT_INDEX : decompose() detail for the FACETED_BREPs of one root of out.stp"""
import sys, os, re, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'patch'))
import lumpsplit
d, ri = sys.argv[1], int(sys.argv[2])
pd = [json.loads(l) for l in open(d + '/occ_roots.jsonl')][ri - 1]['pd']
rx = re.compile(r'#(\d+)\s*=\s*([A-Z_0-9]*)\s*\((.*)\)\s*$', re.S)
ent = {}; buf = ''
for line in open(d + '/out.stp', encoding='latin-1'):
    buf += line
    if not buf.rstrip().endswith(';'): continue
    s, buf = buf.strip()[:-1], ''
    m = rx.match(s)
    if m: ent[int(m.group(1))] = (m.group(2), m.group(3))
refs = lambda s: [int(x) for x in re.findall(r'#(\d+)', s)]
pds = [k for k, (t, b) in ent.items() if t == 'PRODUCT_DEFINITION_SHAPE' and refs(b)[0] == pd][0]
sdr = [k for k, (t, b) in ent.items() if t == 'SHAPE_DEFINITION_REPRESENTATION' and refs(b)[0] == pds][0]
rep = refs(ent[sdr][1])[1]
print('rep', ent[rep][1][:120])
pt = {}
for k, (t, b) in ent.items():
    if t == 'CARTESIAN_POINT':
        pt[k] = tuple(float(x) for x in re.findall(r'[-+0-9.Ee]+', b.split('(', 1)[1])[:3])
for br in refs(ent[rep][1]):
    if ent[br][0] != 'FACETED_BREP': continue
    fids = refs(ent[refs(ent[br][1])[0]][1])
    loops = []
    for f in fids:
        ls = []
        for bid in refs(ent[f][1].split(')', 1)[0]):
            bb = ent[bid][1]; p = refs(ent[refs(bb)[0]][1]); ls.append(p if '.T.' in bb.rsplit(',', 1)[-1] else p[::-1])
        loops.append(ls)
    comps, info = lumpsplit.decompose(loops, pt)
    print('brep', br, 'faces', len(fids), 'loops/face', collections.Counter(len(l) for l in loops), info)
    for c in comps:
        print('   comp faces', len(c['faces']), 'reverse', c['reverse'], 'vol', round(c['vol'], 1))
    if len(sys.argv) > 3:
        for i, l in enumerate(loops):
            print('  face', i, [[pt[q] for q in lp] for lp in l])
