"""newsalv_probe.py KITDIR DB1 : new engines (>= 7.5) - (1) cut parts without an outline: is their outline record outside the runs
(flagged / raw) and does it pass the outline checks? (2) unlinked cut parts: is there an isolated relation record (same layout as the
linked ones) naming them?"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1dec, db1step
data = db1dec.load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
L = json.load(open(os.path.join(KIT, 'layouts.json')))
lay = (L.get('%.2f' % eng) or {}).get('layout'); var = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = db1dec.decode(data, lay, var, True)
M = db1dec.members(db, pts, cs, lay)
links = db.find_cut_links(M); cl = db.cut_layout or {}
print('==', os.path.basename(sys.argv[2])[:16], eng, 'members', len(M), 'cut_layout', cl, 'poly', {k: lay.get(k) for k in ('poly_field', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_cap', 'poly_ch')})
cuts = [m for m in M if m.get('cut')]
PL1 = db1dec.PLATE1_RE if hasattr(db1dec, 'PLATE1_RE') else re.compile(r'^(PL|BL)')
noout = [m for m in cuts if m['prof'] and PL1.match(m['prof']) and db.polygon(lay, m) is None]
print('cut contour parts without outline', len(noout), collections.Counter(m['prof'] for m in noout).most_common(5))
res = collections.Counter()
for m in noout:
    key = int(db.I([m['off'] + lay['poly_field']])[0]); S = lay['poly_stride']; stage = 'hop1'
    if lay.get('poly_field2'):
        r = int(db.lookup([key], S)[0])
        if r < 0:
            fl = db.flagged([key])[key]
            res['hop1_missing_in_runs'] += 1
            if not fl: res['hop1_not_found_anywhere'] += 1; continue
            r = fl[0]; res['hop1_found_flagged'] += 1
        key = int(db.I([r + lay['poly_field2']])[0]); S = lay['poly_stride2']
    recs = db.lookup_all(key, S)
    if recs:
        res['outline_rec_in_runs(but rejected)'] += 1
        if res['outline_rec_in_runs(but rejected)'] <= 3:
            r = recs[0]; cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']
            print('   in-run outline rejected: cut', m['seq'], m['prof'], 'L', round(m['L'], 1), 'u', np.round(db.F(r + ub + 4 * np.arange(cap)), 1).tolist(), 'v', np.round(db.F(r + vb + 4 * np.arange(cap)), 1).tolist())
        continue
    fl = db.flagged([key])[key]
    if not fl: res['outline_not_found'] += 1; continue
    res['outline_found_flagged'] += 1
    r = fl[0]; cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']
    u = db.F(r + ub + 4 * np.arange(cap)); v = db.F(r + vb + 4 * np.arange(cap))
    if res['outline_found_flagged'] <= 4:
        print('   flagged outline: cut', m['seq'], m['prof'], 'L', round(m['L'], 1), 'rec', r, 'flag', int(db.u8[r + 8]), 'u', np.round(u, 1).tolist(), 'v', np.round(v, 1).tolist())
print('outline salvage', dict(res))
# (2) unlinked cuts
if cl:
    fc, fp = cl['cut'], cl['parent']
    seq = lambda m: int(db.I([m['off'] + 9])[0])
    pk = {seq(m) for m in M if not m.get('cut')}
    ln = {c for v in links.values() for c in v}
    un = [m for m in cuts if m['seq'] not in ln]
    r2 = collections.Counter()
    for m in un:
        c = m['seq']; hits = []
        p = data.find(int(c).to_bytes(4, 'little', signed=True))
        while p >= 0:
            st = p - fc
            if st >= 0 and int(db.u8[st + 8]) in (1, 4, 5) and int(db.I([st])[0]) > 0 and int(db.I([st + 4])[0]) > 0:
                par = int(db.I([st + fp])[0])
                hits.append((st, int(db.u8[st + 8]), par, par in pk))
            p = data.find(int(c).to_bytes(4, 'little', signed=True), p + 1)
        ok = [h for h in hits if h[3]]
        r2['salvageable' if ok else 'no_record'] += 1
        if len(ok) > 1 and len({h[2] for h in ok}) > 1: r2['ambiguous'] += 1
        if r2['salvageable'] <= 4 and ok: print('   unlinked cut', c, m['prof'], 'isolated relation records', ok[:3])
    print('unlinked cuts', len(un), dict(r2))
