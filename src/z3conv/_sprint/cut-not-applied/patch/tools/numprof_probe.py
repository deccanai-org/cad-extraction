"""numprof_probe.py KITDIR DB1 : cut parts whose profile is a bare number: raw attribute-record strings, their parents and the
part geometry (L, polygon), new and old engines"""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1dec
data = db1dec.load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
NUMP = re.compile(r'^\d+(\.\d+)?$')
if eng < 7.5:
    import db1old
    M, info, cut_rel = db1old.read(data, eng)
    T = db1old.LAST; attrs = T['attrs']
    par = {c: p for p, cs in cut_rel.items() for c in cs}; byp = {m['pid']: m for m in M}
    sel = [m for m in M if m['cut'] and m['prof'] and NUMP.match(m['prof'])]
    print('==', os.path.basename(sys.argv[2])[:16], eng, 'numeric-profile cut parts', len(sel), collections.Counter(m['prof'] for m in sel).most_common(8))
    allnum = [m for m in M if m['prof'] and NUMP.match(m['prof'])]
    print('   all parts with numeric profile', len(allnum), collections.Counter((m['cut'], m.get('obj_type'), m['mat']) for m in allnum).most_common(6))
    for m in sel[:6]:
        a = attrs.get(m['attr'])
        o = db1old.Old(data)
        q = [int(x) for x in np.nonzero(o.I_all[8:len(o.I_all) - 400] == m['attr'])[0] + 8 if data[int(x) + 7] == 4][:1]
        strs = [t.decode('latin1') for t in re.findall(rb'[\x20-\x7e]{2,}', data[q[0]:q[0] + 373])] if q else None
        p = byp.get(par.get(m['pid']))
        print('   cut', m['pid'], repr(m['prof']), 'L', round(m['L'], 1), 'form', m['form'], 'poly', [[round(c, 1) for c in pt] for pt in (m['old_poly'] or [])][:6],
              '| attr', {k: a[k] for k in ('obj_type', 'ben', 'mat', 'npoints', 'form')} if a else None, 'raw strings', strs,
              '| parent', (p['prof'], round(p['L'])) if p else None)
else:
    import db1step
    L = json.load(open(os.path.join(KIT, 'layouts.json')))
    lay = (L.get('%.2f' % eng) or {}).get('layout'); var = [v['layout'] for v in L.values() if v.get('layout')]
    db, pts, cs, lay = db1dec.decode(data, lay, var, True)
    M = db1dec.members(db, pts, cs, lay)
    links = db.find_cut_links(M)
    par = {c: p for p, cs_ in links.items() for c in cs_}; bys = {m['seq']: m for m in M}
    sel = [m for m in M if m.get('cut') and m['prof'] and NUMP.match(m['prof'])]
    print('==', os.path.basename(sys.argv[2])[:16], eng, 'numeric-profile cut parts', len(sel), collections.Counter(m['prof'] for m in sel).most_common(8))
    allnum = [m for m in M if m['prof'] and NUMP.match(m['prof'])]
    print('   all parts with numeric profile', len(allnum), collections.Counter(bool(m.get('cut')) for m in allnum).most_common(4))
    for m in sel[:6]:
        rr = db.attr_records(lay, m['attr'])
        strs = [t.decode('latin1') for t in re.findall(rb'[\x20-\x7e]{2,}', db.b[rr[0]:rr[0] + lay['attr_stride']])] if rr else None
        pts_ = db.outline_points(lay, m) if lay.get('poly_stride') else None
        p = bys.get(par.get(m['seq']))
        print('   cut', m['seq'], repr(m['prof']), 'L', round(m['L'], 1), 'outline', [[round(c, 1) for c in pt[:2]] for pt in (pts_ or [])][:6],
              '| attr raw strings', strs, '| parent', (p['prof'], round(p['L'])) if p else None)
