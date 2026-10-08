"""endoff_probe.py NAME : old-engine part records of parts whose Tekla Length differs from our reference length: which doubles in the
part record (any 4-byte alignment) explain the difference (end offsets / fitting distances)?"""
import sys, os, re, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
sys.path.insert(0, W + '/kitp3')
import db1old
from db1dec import load
import ifcopenshell, ifcopenshell.guid
data = load(f'{W}/truth/{NAME}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
P = db1old.PART_NEW if eng >= 7.1 else db1old.PART_OLD
o = db1old.Old(data); D = o.D_all; F = o.F_all; I = o.I_all
RX = re.compile(rb'([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
f = ifcopenshell.open(f'{W}/truth/{NAME}.ifc'); tek = {}
for e in f.by_type('IfcElement'):
    q = {}
    for r in e.IsDefinedBy or []:
        if r.is_a('IfcRelDefinesByProperties') and r.RelatingPropertyDefinition.is_a('IfcPropertySet') and r.RelatingPropertyDefinition.Name in ('BaseQuantities', 'Pset_Tekla_General'):
            for x in r.RelatingPropertyDefinition.HasProperties:
                v = getattr(x, 'NominalValue', None)
                if v is not None and isinstance(v.wrappedValue, (int, float)): q[x.Name] = float(v.wrappedValue)
    tek[ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')] = q
G = [(m.start(), m.group(1).decode().upper().replace('-', '')) for m in RX.finditer(data)]
pid2g = {}
for g, s in G:
    if s in tek:
        v = int.from_bytes(data[g - 30:g - 26], 'little', signed=True)
        if v in byp: pid2g.setdefault(v, s)
diffs = []; same = []
for m in M:
    if m['cut'] or m['bolt'] or m['pid'] not in pid2g: continue
    t = tek[pid2g[m['pid']]]
    if 'Length' not in t: continue
    d = t['Length'] - m['L']
    (same if abs(d) <= 0.5 else diffs).append((m, t, d))
print('==', NAME, eng, 'stride', P['stride'], 'diff', len(diffs), 'same', len(same))
# score every double slot in the part record: does it equal d, d/2, -d, -d/2 for the differing parts and 0 for the same-length parts?
S = P['stride']; score = collections.Counter(); zero_ok = collections.Counter()
for off in range(0, S - 8):
    if P['csys'] <= off < P['csys'] + 32: continue
    hit = 0
    for m, t, d in diffs:
        v = float(D[m['off'] + off])
        if np.isfinite(v) and any(abs(v - c) < 0.6 for c in (d, -d, d / 2, -d / 2)) and abs(v) > 0.5: hit += 1
    score[off] = hit
    zero_ok[off] = sum(1 for m, t, d in same if np.isfinite(float(D[m['off'] + off])) and abs(float(D[m['off'] + off])) < 0.5)
for off, h in score.most_common(12):
    print('   double @+%d explains %d of %d differing parts; is ~0 on %d of %d same-length parts' % (off, h, len(diffs), zero_ok[off], len(same)))
# pairs of slots (start/end offsets along the axis): d = b - a ?
best = []
offs = [k for k in range(0, S - 8, 4) if not (P['csys'] <= k < P['csys'] + 32)]
for a in offs:
    va = np.array([float(D[m['off'] + a]) for m, t, d in diffs])
    for b in offs:
        if b == a: continue
        vb = np.array([float(D[m['off'] + b]) for m, t, d in diffs]); dd = np.array([d for m, t, d in diffs])
        with np.errstate(invalid='ignore'):
            ok = np.isfinite(va) & np.isfinite(vb) & (np.abs((vb - va) - dd) < 0.6)
            ok2 = np.isfinite(va) & np.isfinite(vb) & (np.abs((vb + va) - dd) < 0.6)
        best.append((int(ok.sum()), 'b-a', a, b)); best.append((int(ok2.sum()), 'a+b', a, b))
best.sort(reverse=True)
print('   slot pairs:', best[:6])
for m, t, d in diffs[:5]:
    print('   part', m['pid'], m['prof'], 'L %.1f tekla %.1f d %.1f' % (m['L'], t['Length'], d), 'doubles', [(k, round(float(D[m['off'] + k]), 2)) for k in range(56, S - 8, 4) if np.isfinite(D[m['off'] + k]) and 0.3 < abs(D[m['off'] + k]) < 1e5][:16])
