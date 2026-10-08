"""arc40_probe.py KITDIR DB1... : contour points of type 40 ('arc point'): is the point ON the arc through its neighbours, or the
arc CENTRE (equidistant from both neighbours)? statistics per model, plates and cut parts, plus refused outlines"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1dec
L = json.load(open(os.path.join(KIT, 'layouts.json'))); var = [v['layout'] for v in L.values() if v.get('layout')]
for f in sys.argv[2:]:
    try:
        data = db1dec.load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
        lay = (L.get('%.2f' % eng) or {}).get('layout')
        db, pts, cs, lay = db1dec.decode(data, lay, var, True)
        M = db1dec.members(db, pts, cs, lay)
    except Exception as ex:
        print('==', os.path.basename(f), 'decode failed', ex); continue
    st = collections.Counter(); ex = []
    for m in M:
        if not (m.get('prof') or '').upper().startswith(('PL', 'BL')) and not m.get('cut'): continue
        try: P = db.outline_points(lay, m)
        except Exception: P = None
        if not P: continue
        n = len(P); grp = 'cut' if m.get('cut') else 'plate'
        t40 = [i for i in range(n) if P[i][2] == 40]
        if not t40: continue
        st[grp + '_with40'] += 1
        refused = db.polygon(lay, m) is None
        st[grp + '_refused'] += refused
        for i in t40:
            a = np.array(P[i - 1][:2]); b = np.array(P[i][:2]); c = np.array(P[(i + 1) % n][:2])
            if P[i - 1][2] == 40 or P[(i + 1) % n][2] == 40: st[grp + '_run40'] += 1; continue
            da, dc = np.linalg.norm(b - a), np.linalg.norm(b - c)
            eq = abs(da - dc) <= 1e-3 * max(da, dc, 1)
            st[grp + ('_equidistant' if eq else '_not_equidistant') + ('_refused' if refused else '')] += 1
            if len(ex) < 8 and (refused or eq): ex.append((grp, m.get('seq'), m.get('prof'), round(float(da), 3), round(float(dc), 3), refused, [tuple(round(x, 2) for x in p[:3]) for p in P][:8]))
    print('==', os.path.basename(f)[:20], eng, dict(st))
    for e in ex: print('   ', e)
