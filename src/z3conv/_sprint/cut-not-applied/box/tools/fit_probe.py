"""fit_probe.py NAME : fittings / line cuts in an old-engine model with a Tekla IFC export of the same model.
Tekla 'Length' (BaseQuantities) vs our reference length L per part; for parts Tekla shortens: the relations (any stride/type) naming
the part and the records of the related objects (points / planes)."""
import sys, os, re, json, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
sys.path.insert(0, W + '/kitp2')
import db1old
from db1dec import load
import ifcopenshell, ifcopenshell.guid
np.set_printoptions(suppress=True, precision=2, linewidth=220)
data = load(f'{W}/truth/{NAME}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
RX = re.compile(rb'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
G = [(m.start(), m.group(1).decode().upper().replace('-', '')) for m in RX.finditer(data)]
pid2g = {}; gpos = {}
for g, s in G:
    v = int.from_bytes(data[g - 8:g - 4], 'little', signed=True)
    pid2g.setdefault(v, s); gpos.setdefault(v, g - 8)
f = ifcopenshell.open(f'{W}/truth/{NAME}.ifc')
tek = {}
for e in f.by_type('IfcElement'):
    q = {}
    for r in e.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties') and r.RelatingPropertyDefinition.is_a('IfcPropertySet') and r.RelatingPropertyDefinition.Name in ('BaseQuantities', 'Pset_Tekla_General'):
            for x in r.RelatingPropertyDefinition.HasProperties:
                v = getattr(x, 'NominalValue', None)
                if v is not None and isinstance(v.wrappedValue, (int, float)): q[x.Name] = float(v.wrappedValue)
    tek[ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')] = q
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
# all relation-like records (stride 17 and 61 runs), every type
rv = np.zeros(N, bool); Mr = N - 20
rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
rels = collections.defaultdict(list)
for rs in (17, 61):
    for q in o.runs(rv, rs):
        t, a, b = int(I[q + 4]), int(I[q + 8]), int(I[q + 12])
        rels[a].append((t, 'id1', b, rs)); rels[b].append((t, 'id2', a, rs))
diff = []; st = collections.Counter()
for m in M:
    if m['cut'] or m['bolt']: continue
    t = tek.get(pid2g.get(m['pid']))
    if not t or 'Length' not in t: st['no_tekla'] += 1; continue
    d = m['L'] - t['Length']
    st['shorter_in_tekla' if d > 1.0 else ('longer_in_tekla' if d < -1.0 else 'same')] += 1
    if abs(d) > 1.0: diff.append((m, t, d))
print('==', NAME, eng, 'parts', len(M), dict(st))
print('   L - Tekla Length (mm) distribution', np.percentile([x[2] for x in diff], [5, 25, 50, 75, 95]) if diff else None)
tc = collections.Counter(); tc_same = collections.Counter()
same = [m for m in M if not m['cut'] and not m['bolt'] and tek.get(pid2g.get(m['pid'])) and abs(m['L'] - tek[pid2g[m['pid']]].get('Length', -1e9)) <= 1.0]
for m, t, d in diff:
    for r in rels.get(m['pid'], []): tc[(r[0], r[1], r[3])] += 1
for m in same:
    for r in rels.get(m['pid'], []): tc_same[(r[0], r[1], r[3])] += 1
print('   relations per part, parts Tekla shortens (n=%d):' % len(diff), [(k, round(v / max(1, len(diff)), 2)) for k, v in tc.most_common(10)])
print('   relations per part, parts with equal length (n=%d):' % len(same), [(k, round(v / max(1, len(same)), 2)) for k, v in tc_same.most_common(10)])
for m, t, d in diff[:6]:
    print('  part', m['pid'], m['prof'], 'L %.1f tekla %.1f diff %.1f' % (m['L'], t['Length'], d), 'O', np.round(m['O'], 1), 'E', np.round(m['E'], 1),
          'tekla start', [t.get(k) for k in ('StartX', 'StartY', 'StartZ')], 'end', [t.get(k) for k in ('EndX', 'EndY', 'EndZ')])
    for r in rels.get(m['pid'], [])[:8]:
        oid = r[2]; ob = byp.get(oid)
        recs = [int(q) for q in np.nonzero(I[8:N] == oid)[0] + 8 if data[int(q) - 1] == 4][:3]
        print('      rel type', r[0], r[1], 'stride', r[3], 'other', oid, (ob['prof'] if ob else '-'), 'live records', [(q, [int(I[q + 4 * k]) for k in range(1, 6)], [round(float(D[q + 8 + 8 * k]), 2) for k in range(7)]) for q in recs])
