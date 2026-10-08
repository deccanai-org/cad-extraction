"""Old engines (6.x-7.4x): every ANTIMATERIAL cut part -> built? linked (relation type 11)? parents written?
usage: old_cut_audit.py KITDIR DB1..."""
import sys, os, re, json, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old, db1step, db1prof
from db1dec import load
cat = json.load(open(os.path.join(KIT, 'tekla_profiles.json')))
for f in sys.argv[2:]:
    data = load(f); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
    M, info, cut_rel = db1old.read(data, eng)
    M = [m for m in M if not db1prof.is_null_record(m)]
    byp = {m['pid']: m for m in M}
    dropped = {m['pid'] for m in M if m.get('axis_ok') is False}
    parents_of = collections.defaultdict(list)
    for p, cs in cut_rel.items():
        for c in cs: parents_of[c].append(p)
    # relation histogram (all types) for context
    o = db1old.Old(data); I = o.I_all; N = len(I) - 400
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    rel_off = o.runs(rv, 17)
    types = collections.Counter(int(I[q + 4]) for q in rel_off)
    cuts = [m for m in M if m.get('cut')]
    st = collections.Counter(); rows = []
    for m in cuts:
        kind, v, how = db1step.section_for(m['prof'], cat)
        built = None
        if m.get('axis_ok') is False: built = 'axis_dropped'
        elif kind is None and v == 'contour_plate':
            P = m.get('old_poly') or []
            nz = [p for p in P if any(abs(c) > 0 for c in p)]
            built = 'contour' if len(P) >= 3 and len(nz) >= 3 else ('contour_no_outline(npts=%d,nonzero=%d)' % (len(P), len(nz)))
        elif kind is None: built = 'unresolved:' + str(v)
        else: built = 'profile:' + kind
        par = parents_of.get(m['pid'], [])
        pst = []
        for p in par:
            pm = byp.get(p)
            if pm is None: pst.append('parent_not_decoded')
            elif p in dropped: pst.append('parent_axis_dropped')
            elif pm.get('cut'): pst.append('parent_is_cut')
            elif pm.get('bolt'): pst.append('parent_is_bolt')
            else: pst.append('parent_ok')
        key = (built.split('(')[0].split(':')[0], 'linked' if par else 'unlinked', ','.join(sorted(set(pst))) or '-')
        st[key] += 1
        rows.append((m['pid'], m['prof'], built, par, pst))
    # relations type 11 whose child is not a cut part
    nonc = collections.Counter()
    for p, cs in cut_rel.items():
        for c in cs:
            cm = byp.get(c)
            nonc['child_not_decoded' if cm is None else ('child_cut' if cm.get('cut') else ('child_bolt' if cm.get('bolt') else 'child_part:' + str(cm.get('prof'))[:12]))] += 1
    print('==', os.path.basename(f)[:16], eng, 'parts', len(M), 'cuts', len(cuts), 'rel types', types.most_common(12))
    print('   type-11 relations', sum(len(v) for v in cut_rel.values()), dict(nonc.most_common(10)))
    for k, v in sorted(st.items(), key=lambda kv: -kv[1]): print('   ', v, k)
    for r in rows:
        if not r[2].startswith(('contour', 'profile')) or not r[3] or 'parent_ok' not in r[4]:
            print('      ', r)
