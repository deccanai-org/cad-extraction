"""patch_audit2.py KIT_IN KIT_OUT (v2: per hole span + Tekla relation flag): copy a db1 kit and add an audit dump to db1step.convert_old (geometry unchanged).
DB1_AUDIT=<path> -> json {bolts: per bolt (group, axis, d, L, flags, grip, hits, ply spans, collisions of head/washers/nuts with
other written parts), parts: per written/skipped part (profile, how, outline known), groups: per bolt-group record}"""
import sys, os, shutil
src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for fn in os.listdir(src):
    p = os.path.join(src, fn)
    if os.path.isfile(p) or os.path.islink(p):
        if os.path.lexists(os.path.join(dst, fn)): os.remove(os.path.join(dst, fn))
        if os.path.islink(p): os.symlink(os.readlink(p), os.path.join(dst, fn))
        else: shutil.copy2(p, dst)
t = open(os.path.join(src, 'db1step.py')).read()
anchor = "    st.update(written=len(out.elems), sources=dict(src), skipped=dict(why), horizontal=len(hz), cuts_applied=applied,"
assert t.count(anchor) == 1, 'anchor'
hook = r'''    if os.environ.get('DB1_AUDIT'):
        import json as _json
        _inv = collections.defaultdict(list)
        _pid = {id(m): m.get('pid') for m in M}
        for k_, v_ in part_bolts.items():
            for i_ in v_:
                _inv[i_].append(_pid[k_])
        _f = lambda v: [float(x) for x in v]
        # collision probes: axis segments of head / washers / nuts (decoded placement) against every written part's uncut solid
        _cand = [(m, bodies.get(id(m)), REGION.get(id(m))) for m in M if not m.get('cut') and not m.get('bolt')]
        _cand = [(m, b_, r_) for m, b_, r_ in _cand if b_ and b_[0] is not None and r_ is not None]
        _ab = [db1bolts.aabb_of_part(b_[0], b_[2], r_) for m, b_, r_ in _cand]
        _lo = np.array([x[0] for x in _ab]) if _ab else np.zeros((0, 3)); _hi = np.array([x[1] for x in _ab]) if _ab else np.zeros((0, 3))
        def _probe(pt, ez, z0, z1, d):
            if z1 - z0 <= 0.4 or not len(_lo):
                return []
            a, b = z0 + 0.2, z1 - 0.2
            fake = {'c': pt + ez * ((a + b) / 2), 'ez': ez, 'L': b - a, 'd': d}
            lo_ = np.minimum(pt + ez * a, pt + ez * b) - d; hi_ = np.maximum(pt + ez * a, pt + ez * b) + d
            hits_ = []
            for k_ in np.nonzero(np.all(_hi >= lo_, axis=1) & np.all(_lo <= hi_, axis=1))[0]:
                m, b_, r_ = _cand[k_]
                if db1bolts.part_hit(b_[0], b_[2], r_, fake):
                    hits_.append(m.get('pid'))
            return hits_
        _R = getattr(db1old, 'REL', None)
        if not _R:
            _o = db1old.Old(data); _N = len(_o.I_all) - 400; _I = _o.I_all
            _rv = np.zeros(_N, bool); _Mr = _N - 20
            _rv[:_Mr] = (_I[:_Mr] > 0) & (_I[4:_Mr + 4] >= 0) & (_I[4:_Mr + 4] <= 2000) & (_I[8:_Mr + 8] > 0) & (_I[12:_Mr + 12] > 0)
            _R = {}
            for q in _o.runs(_rv, 61 if engine >= 7.1 else 17):
                if int(_I[q + 4]) in (10, 11): _R.setdefault(int(_I[q + 4]), []).append((int(_I[q + 8]), int(_I[q + 12])))
            del _o, _I, _rv
        _rel = collections.defaultdict(set)
        for a_, b_ in _R.get(10, []):
            _rel[a_].add(b_); _rel[b_].add(a_)
        _mb = {m.get('pid'): (bodies.get(id(m)), REGION.get(id(m))) for m in M if not m.get('cut') and not m.get('bolt')}
        _bl = []
        for i_, bb in enumerate(BL):
            rec = {'i': i_, 'gid': bb.get('pid'), 'c': _f(bb['c']), 'ez': _f(bb['ez']), 'ex': _f(bb['ex']), 'd': bb['d'], 'd_stored': bb.get('d_stored'),
                   'L': bb['L'], 'holes_only': bb.get('holes_only'), 'axial': bb.get('axial_decoded'), 'head_up': bb.get('head_up'), 'shift': bb.get('shift'),
                   'grip': bb.get('grip'), 'zh': bb.get('zh'), 'tol': bb.get('tol'), 'wash_head': bb.get('wash_head'), 'wash_nut': bb.get('wash_nut'),
                   'wash_2': bb.get('wash_2'), 'nuts': bb.get('nuts'), 'standard': bb.get('standard'), 'std_src': (bb.get('std') or {}).get('source'),
                   'std_family': (bb.get('std') or {}).get('family'), 'hits': _inv.get(i_, []), 'spans': spans[i_] if BL else [],
                   'rel_n': len(_rel.get(bb.get('pid'), ()))}
            hd = []
            for p_ in _inv.get(i_, []):
                b_, r_ = _mb.get(p_, (None, None))
                sp_ = db1bolts.ply_check(b_[0], b_[2], r_, bb) if b_ and b_[0] is not None and r_ is not None else None
                hd.append([p_, round(sp_[0], 2) if sp_ else None, round(sp_[1], 2) if sp_ else None, (p_ in _rel[bb.get('pid')]) if _rel.get(bb.get('pid')) else None])
            rec['hit_detail'] = hd
            rec['rel_parts'] = sorted(_rel.get(bb.get('pid'), ()))[:40]
            if bb.get('axial_decoded') and not bb.get('holes_only') and _cand:
                c_ = np.asarray(bb['c'], float); ez_ = np.asarray(bb['ez'], float); L_ = bb['L']
                pt = c_ - ez_ * (bb['zh'] - L_ / 2)
                sg = bb.get('std')
                hh = sg['head_h'] if sg else 0.65 * bb['d']; hn = sg['nut_h'] if sg else 0.8 * bb['d']
                wod, wt = db1bolts.washer_dims(bb)
                g0, g1 = bb['grip']
                pr = {}
                if bb.get('wash_head'):
                    pr['head_washer'] = (g1, g1 + wt)
                pr['head'] = (bb['zh'], bb['zh'] + hh)
                z = g0; nw = (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0)
                if nw:
                    pr['nut_washers'] = (z - nw * wt, z); z -= nw * wt
                nn = max(1, bb.get('nuts') or 1) if bb.get('nuts', 1) else 0
                if nn:
                    pr['nuts'] = (z - nn * hn, z)
                rec['probe'] = {k: [round(v[0], 2), round(v[1], 2), _probe(pt, ez_, v[0], v[1], bb['d'])] for k, v in pr.items()}
                rec['wt'] = wt; rec['wod'] = wod; rec['hh'] = hh; rec['hn'] = hn
            _bl.append(rec)
        _parts = {}
        for m in M:
            if m.get('cut') or m.get('bolt'):
                continue
            b_ = bodies.get(id(m))
            _parts[str(m.get('pid'))] = {'prof': m.get('prof'), 'how': (b_[3] if b_ and b_[0] is not None else (b_[1] if b_ else None)),
                                         'region': REGION.get(id(m)) is not None, 'cuts': len(cut_rel.get(m['pid'], []))}
        _groups = {str(m.get('pid')): {'prof': m.get('prof'), 'mat': m.get('mat'), 'n_pts': len(m.get('old_poly') or []), 'cut': bool(m.get('cut'))}
                   for m in M if m.get('bolt')}
        _json.dump({'engine': engine, 'bolts_on': BOLTS_ON, 'bolts': _bl, 'parts': _parts, 'groups': _groups}, open(os.environ['DB1_AUDIT'], 'w'))
'''
t = t.replace(anchor, hook + anchor)
open(os.path.join(dst, 'db1step.py'), 'w').write(t)
print('patched', dst)
