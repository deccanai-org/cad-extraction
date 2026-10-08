"""oldfit_probe.py NAME [SRC] : old-engine (6.87-7.30) Tekla fittings (relation type 9) and line cuts (type 12).
Child object record hypothesis: id@0, key@4, point x,y,z@8/16/24 (doubles), value@32. Tests whether key@4 is a coordsys_attr id
and which axis of that csys is the plane normal, against Tekla's own IFC 'Length' (truth models) per part."""
import sys, os, re, json, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
KIT = os.environ.get('KIT', W + '/kitnp'); sys.path.insert(0, KIT)
import db1old
from db1dec import load
np.set_printoptions(suppress=True, precision=3, linewidth=220)
src = sys.argv[2] if len(sys.argv) > 2 else (f'{W}/truth/{NAME}.db1' if os.path.exists(f'{W}/truth/{NAME}.db1') else f'{W}/src/{NAME}.db1')
data = load(src); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
o = db1old.Old(data); I = o.I_all; D = o.D_all; N = len(I) - 400
# csys table (same as db1old)
cv = np.zeros(N, bool); Mx = N - 60
x = np.stack([D[k:Mx + k] for k in (0, 8, 16)], 1); y = np.stack([D[k:Mx + k] for k in (24, 32, 40)], 1)
with np.errstate(invalid='ignore', over='ignore'):
    cv[:Mx] = (np.abs((x * x).sum(1) - 1) < 0.02) & (np.abs((y * y).sum(1) - 1) < 0.02) & (I[48:Mx + 48] > 0)
csa = {int(I[q + 48]): (np.array([D[q], D[q + 8], D[q + 16]]), np.array([D[q + 24], D[q + 32], D[q + 40]])) for q in o.runs(cv, 53)}
del x, y, cv
# relations
rv = np.zeros(N, bool); Mr = N - 20
rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
rel = collections.defaultdict(list); rs_used = collections.Counter()
for rs in (17, 61):
    for q in o.runs(rv, rs):
        t = int(I[q + 4])
        if t in (9, 12, 34, 13):
            rel[t].append((int(I[q + 8]), int(I[q + 12]))); rs_used[(t, rs)] += 1
print('==', NAME, eng, 'parts', len(M), 'csa', len(csa), 'relations', {t: len(v) for t, v in rel.items()}, dict(rs_used))
# child records: live copies (prefix 4) whose id@0 = child id, with a plausible point @8
u8 = o.u8
def child_recs(cid):
    out = []
    for q in np.nonzero(I[:N] == cid)[0]:
        q = int(q)
        if u8[q - 1] != 4: continue
        P = np.array([D[q + 8], D[q + 16], D[q + 24]])
        if not np.all(np.isfinite(P)) or np.any(np.abs(P) > 1e8) or not np.any(P != 0): continue
        if int(I[q + 4]) not in csa: continue
        out.append(q)
    return out
# Tekla truth (optional)
tek = {}; pid2g = {}
ifcp = f'{W}/truth/{NAME}.ifc'
if os.path.exists(ifcp):
    import ifcopenshell, ifcopenshell.guid
    f = ifcopenshell.open(ifcp)
    for e in f.by_type('IfcElement'):
        q = {}
        for r in e.IsDefinedBy or []:
            if r.is_a('IfcRelDefinesByProperties'):
                pd = r.RelatingPropertyDefinition
                if pd.is_a('IfcPropertySet') and pd.Name in ('BaseQuantities', 'Pset_Tekla_General'):
                    for x_ in pd.HasProperties:
                        v = getattr(x_, 'NominalValue', None)
                        if v is not None and isinstance(v.wrappedValue, (int, float)): q[x_.Name] = float(v.wrappedValue)
                elif pd.is_a('IfcElementQuantity'):
                    for x_ in pd.Quantities:
                        if x_.is_a('IfcQuantityLength'): q.setdefault(x_.Name, float(x_.LengthValue))
        tek[ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')] = q
    RX = re.compile(rb'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
    for mm in RX.finditer(data):
        v = int.from_bytes(data[mm.start() - 8:mm.start() - 4], 'little', signed=True)
        pid2g.setdefault(v, mm.group(1).decode().upper().replace('-', ''))
print('   truth parts with Tekla Length', sum(1 for m in M if 'Length' in tek.get(pid2g.get(m['pid']), {})))
for T in (9, 12):
    st = collections.Counter(); keys = collections.Counter(); vals = collections.Counter(); ex = []
    per_part = collections.defaultdict(list)
    for a, b in rel.get(T, []):
        m = byp.get(a)
        st['parent_decoded' if m else 'parent_not_decoded'] += 1
        qs = child_recs(b); st['child_recs_%d' % min(len(qs), 3)] += 1
        if not qs or not m: continue
        q = qs[0]; k4 = int(I[q + 4]); st['key4_in_csa' if k4 in csa else 'key4_not_csa'] += 1
        vals[round(float(D[q + 32]), 2)] += 1
        P = np.array([D[q + 8], D[q + 16], D[q + 24]])
        if k4 in csa:
            cx, cy = csa[k4]; per_part[a].append((P, cx, cy, float(D[q + 32]), b, q))
    print(f' type {T}:', dict(st), 'value@32 top', vals.most_common(8))
    if not per_part: continue
    # hypotheses for the plane normal, tested on the predicted axis length vs Tekla Length
    H = {'z=x*y': lambda cx, cy: np.cross(cx, cy), 'x': lambda cx, cy: cx, 'y': lambda cx, cy: cy}
    for hn, hf in H.items():
        res = collections.Counter(); errs = []
        for pid, fl in per_part.items():
            m = byp[pid]; O, xa, L = m['O'], m['x'], m['L']
            t0, t1 = 0.0, L; perp = True
            for P, cx, cy, v32, b, q in fl:
                n = hf(cx, cy); n = n / np.linalg.norm(n); c = float(n @ xa)
                if abs(c) < 1e-6: res['plane_parallel_axis'] += 1; continue
                if abs(abs(c) - 1) > 1e-4: perp = False
                tp = float((P - O) @ n) / c
                mid = O + xa * L / 2
                far_pos = float((mid - P) @ n) < 0          # the middle is on the -n side -> the +n side is removed
                res['sign +n_removed' if far_pos else 'sign -n_removed'] += 1
                res['ext' if (tp < 0 or tp > L) else 'trim'] += 1
                if tp < L / 2: t0 = tp
                else: t1 = tp
            tl = tek.get(pid2g.get(pid), {}).get('Length')
            if T == 9:
                pred = t1 - t0
                if tl is None: res['no_truth'] += 1; continue
                d0 = abs(L - tl); d1 = abs(pred - tl)
                key = ('perp' if perp else 'oblique')
                res[key + (' pred_within1mm' if d1 <= 1 else (' L_within1mm' if d0 <= 1 else ' neither'))] += 1
                if perp: errs.append(pred - tl)
        print(f'   hyp n={hn}:', dict(res), 'perp pred-Tekla pct', np.round(np.percentile(errs, [5, 50, 95]), 2) if errs else None)
    for pid, fl in list(per_part.items())[:5]:
        m = byp[pid]; tl = tek.get(pid2g.get(pid), {}).get('Length')
        print('   part', pid, m['prof'], 'L %.1f' % m['L'], 'tekla', tl, 'O', np.round(m['O'], 1), 'x', np.round(m['x'], 3))
        for P, cx, cy, v32, b, q in fl:
            print('      child', b, 'P', np.round(P, 2), 'cx', np.round(cx, 3), 'cy', np.round(cy, 3), 'v32', v32, 'ints', [int(I[q + 4 * k]) for k in range(0, 12)], 'dbl40+', [round(float(D[q + 40 + 8 * k]), 3) for k in range(5)])
