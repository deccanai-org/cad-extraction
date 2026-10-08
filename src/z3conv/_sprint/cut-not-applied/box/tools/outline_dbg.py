"""outline_dbg.py KITDIR DB1 [N] : new engines - why do cut contour parts get no outline? step-by-step outline_points"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1dec
data = db1dec.load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1)); NSHOW = int(sys.argv[3]) if len(sys.argv) > 3 else 4
L = json.load(open(os.path.join(KIT, 'layouts.json')))
lay = (L.get('%.2f' % eng) or {}).get('layout'); var = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = db1dec.decode(data, lay, var, True)
M = db1dec.members(db, pts, cs, lay)
print('==', os.path.basename(sys.argv[2])[:16], eng, 'members', len(M), 'poly', {k: lay.get(k) for k in ('poly_field', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_cap', 'poly_ch', 'poly_f64', 'poly_ub', 'poly_vb')})
cuts = [m for m in M if m.get('cut')]
plates = [m for m in M if not m.get('cut') and (m.get('prof') or '').upper().startswith(('PL', 'BL'))]
why = collections.Counter(); shown = 0
for grp, ms in (('cut', cuts), ('plate', plates)):
    why = collections.Counter(); profs = collections.Counter(); shown = 0
    for m in ms:
        P = db.polygon(lay, m)
        if P is not None: why['ok'] += 1; continue
        pts_ = db.outline_points(lay, m)
        if pts_:
            why['outline_ok_but_polygon_refused'] += 1; reason = 'polygon_refused'
        else:
            # replicate outline_points to find the failing step
            key = int(db.I([m['off'] + lay['poly_field']])[0]); S = lay['poly_stride']; reason = None
            if lay.get('poly_field2'):
                r = int(db.lookup([key], S)[0])
                if r < 0: reason = 'hop1_missing'
                else:
                    key = int(db.I([r + lay['poly_field2']])[0]); S = lay['poly_stride2']
                    if key <= 0: reason = 'hop2_key<=0'
            recs = db.lookup_all(key, S) if reason is None else []
            if reason is None and not recs: reason = 'no_outline_record'
            if reason is None:
                cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']; es, cxo, cyo, tyo = db._poly_offsets(lay); RD = db.D if es == 8 else db.F
                r = recs[0]; u = RD(r + ub + es * np.arange(cap)); v = RD(r + vb + es * np.arange(cap))
                ty = db.I(r + tyo + 4 * np.arange(cap)) if lay.get('poly_ch') else None
                us = [x for x in u if np.isfinite(x)]
                if not np.all(np.isfinite(u[:3])): reason = 'nonfinite'
                elif abs(u[1] - m['L']) > 0.05 and abs(max(us) - min(us) - m['L']) > 0.05: reason = 'L_check'
                else: reason = 'other(area/n)'
                if shown < NSHOW:
                    shown += 1
                    print(f'   {grp} {m["seq"]} {m["prof"]} L {m["L"]:.3f} reason {reason} nrecs {len(recs)} u {np.round(u, 3).tolist()} v {np.round(v, 3).tolist()} ty {None if ty is None else ty.tolist()}')
        why[reason] += 1; profs[(reason, (m.get('prof') or '')[:6])] += 1
    print(grp, len(ms), dict(why), profs.most_common(8))
