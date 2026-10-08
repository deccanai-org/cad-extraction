import sys, json, re, collections, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
L = json.load(open('/opt/db1v2/layouts.json')); variants = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = decode(sys.argv[1], L['8.62']['layout'], variants, False)
print('LAY', {k: lay.get(k) for k in ('fast', 'semi', 'stride', 'csys', 'csys_key', 'attr', 'attr_stride', 'prof_off', 'rest_ref', 'rest_stride', 'poly_field', 'poly_stride')})
M = members(db, pts, cs, lay)
nop = [m for m in M if not m['prof'] and not m['cut']]
print('members', len(M), 'noprof', len(nop))
# where do the no-profile members' attr refs point?
c = collections.Counter(); ex = []
for m in nop[:3000]:
    hits = [(s, o) for s, (K, O) in db.seqidx.items() for o in [int(db.lookup([m['attr']], s)[0])] if o >= 0]
    c[tuple(sorted(s for s, o in hits))] += 1
    if len(ex) < 3 and hits: ex.append((m['attr'], hits[:3]))
print('noprof attr targets', c.most_common(6))
for a, hits in ex:
    for s, o in hits[:2]:
        print('  attr', a, 'stride', s, [(mm.start(), mm.group().decode('latin1')) for mm in re.finditer(rb'[\x20-\x7e]{2,}', db.b[o:o + min(s, 400)])][:10])
# plates
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print('contour plate members', len(cp))
offs = np.array([m['off'] for m in cp[:2000]]); Lm = np.array([m['L'] for m in cp[:2000]])
for f in range(9, lay['stride'] - 3, 4):
    vals = db.I(offs + f)
    for T in db._strides_holding(np.unique(vals), 0.5)[:3]:
        ro = db.lookup(vals, T); ok = ro >= 0
        best = max(((float(np.mean(np.abs(db.F(ro[ok] + ub + 4) - Lm[ok]) < 0.05)), ub) for ub in range(9, T - 16)), default=(0, 0))
        print('  plate field', f, 'T', T, 'resolve', round(ok.mean(), 2), 'best u1==L frac', best)
