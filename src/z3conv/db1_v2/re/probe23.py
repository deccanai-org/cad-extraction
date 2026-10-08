"""survey: profile-less members -> attr record stride + obj_type@13; member+29 -> record stride; sentinel pattern"""
import sys, numpy as np, collections
from cache import *
SENT = 2147483647
for p in sys.argv[1:]:
    db, pts, cs, lay, M = get(p)
    eng = db.b[7:12]
    nop = [m for m in M if not m['prof'] and not m.get('cut')]
    mm = [m for m in M if m['prof'] and m['prof'].startswith('MM')]
    st = collections.Counter(int(db.lookup_stride([m['attr']])[0]) for m in nop if m['attr'])
    ob = collections.Counter()
    for m in nop[:3000]:
        if not m['attr']: continue
        rr = db.attr_records(lay, m['attr'])
        if rr: ob[(int(db.lookup_stride([m['attr']])[0]), int(db.I([rr[0] + 13])[0]))] += 1
    pf = lay.get('poly_field') or 29
    ps = collections.Counter(); sent = collections.Counter()
    for m in (nop[:2000] if nop else mm[:2000]):
        k = int(db.I([m['off'] + pf])[0]); s = int(db.lookup_stride([k])[0]); ps[s] += 1
        for r in db.lookup_all(k, s)[:1] if s > 0 else []:
            for ub in (21,):
                ty = db.I(r + ub + 200 + 4 * np.arange(10)); e = np.nonzero(ty == SENT)[0]
                sent[(s, int(e[0]) if len(e) else -1)] += 1
    print(p.split('/')[-1], eng, 'members', len(M), 'noprof', len(nop), 'MM', len(mm), 'lay attr_stride', lay.get('attr_stride'), 'poly', pf, lay.get('poly_stride'))
    print('   noprof attr strides', st.most_common(5), 'objtype', ob.most_common(6))
    print('   poly-field target strides', ps.most_common(4), 'sentinel idx', sent.most_common(8))
