"""a944_probe.py KITDIR DB1 : why are the BL25 cut outlines of a944 rejected? dump the record arrays + each check"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1dec
data = db1dec.load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
L = json.load(open(os.path.join(KIT, 'layouts.json')))
lay = (L.get('%.2f' % eng) or {}).get('layout'); var = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = db1dec.decode(data, lay, var, True)
M = db1dec.members(db, pts, cs, lay)
cuts = [m for m in M if m.get('cut') and m['prof'] == 'BL25']
bad = [m for m in cuts if db.polygon(lay, m) is None]
print('BL25 cuts', len(cuts), 'no polygon', len(bad))
cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']; A = 4 * cap
for m in bad[:3] + [m for m in cuts if m not in bad][:2]:
    key = int(db.I([m['off'] + lay['poly_field']])[0]); recs = db.lookup_all(key, lay['poly_stride'])
    print('cut', m['seq'], 'L', round(m['L'], 2), 'key', key, 'recs', recs[:3], 'outline_points', db.outline_points(lay, m))
    for r in recs[:2]:
        print('   idx@13', int(db.I([r + 13])[0]), 'u', np.round(db.F(r + ub + 4 * np.arange(cap)), 2).tolist())
        print('   v', np.round(db.F(r + vb + 4 * np.arange(cap)), 2).tolist())
        print('   w', np.round(db.F(r + ub + 2 * A + 4 * np.arange(cap)), 2).tolist())
        print('   cx', np.round(db.F(r + ub + 3 * A + 4 * np.arange(cap)), 2).tolist(), 'cy', np.round(db.F(r + ub + 4 * A + 4 * np.arange(cap)), 2).tolist())
        print('   ty', db.I(r + ub + 5 * A + 4 * np.arange(cap)).tolist())
    pp = db.outline_points(lay, m)
    if pp:
        print('   chamfered', db1dec.apply_chamfers(pp))
