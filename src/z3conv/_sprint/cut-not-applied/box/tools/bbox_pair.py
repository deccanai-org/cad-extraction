"""bbox_pair.py NAME DIR_A DIR_B [N] : (paired bbox_truth) parts written uncut in both runs; per part bbox / centroid error vs Tekla IFC in A and B -> per part, our IFC solid vs Tekla's own IFC solid of the same part (GUID join): bounding box of each
in OUR part frame (x along the member, y, z section axes) -> section-centre offset (dy, dz) and extents, by profile family"""
import sys, os, re, json, gzip, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME, DA, DB = sys.argv[1], sys.argv[2], sys.argv[3]; I0 = int(sys.argv[4]) if len(sys.argv) > 4 else 0; I1 = int(sys.argv[5]) if len(sys.argv) > 5 else 10**9; NMAX = 10**9
sys.path.insert(0, os.environ.get('KIT', W + '/kitnp4'))
import db1old
from db1dec import load
import ifcopenshell, ifcopenshell.geom, ifcopenshell.guid, ifcopenshell.util.placement as up
data = load(f'{W}/truth/{NAME}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
T = ifcopenshell.open(f'{W}/truth/{NAME}.ifc')
tg = {ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', ''): e for e in T.by_type('IfcElement') if e.Representation}
RX = re.compile(rb'([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
G = [(mm.start(), mm.group(1).decode().upper().replace('-', '')) for mm in RX.finditer(data)]
keys = np.array(sorted(byp), np.int64); u8 = np.frombuffer(data, np.uint8); pos = np.array([p for p, g in G if g in tg], np.int64)
best = None
for k in range(2, 80):
    p = pos - k; ok = p >= 0; v = np.zeros(len(p), np.int64); v[ok] = u8[p[ok][:, None] + np.arange(4)].copy().view('<i4')[:, 0]
    i = np.searchsorted(keys, v); i[i >= len(keys)] = 0; n = int((keys[i] == v).sum())
    if best is None or n > best[1]: best = (k, n)
pid2g = {}
for g, s_ in G:
    v = int.from_bytes(data[g - best[0]:g - best[0] + 4], 'little', signed=True)
    if v in byp: pid2g.setdefault(v, s_)

def load(D):
    f = ifcopenshell.open(os.path.join(D, 'model.ifc')); g = {e.GlobalId: e for e in f.by_type('IfcElement')}
    return {p[0]: (p, g.get(p[5])) for p in json.load(gzip.open(os.path.join(D, 'convert.json.parts.json.gz'), 'rt')) if p[3] == 'written' and p[5] and not p[6]}
A, B = load(DA), load(DB)
gs = ifcopenshell.geom.settings(); gs.set(gs.USE_WORLD_COORDS, True)
def verts(e):
    try:
        sh = ifcopenshell.geom.create_shape(gs, e); V = np.array(sh.geometry.verts).reshape(-1, 3)
        return V * 1000.0 if np.abs(V).max() < 2e4 else V
    except Exception: return None
def fam(p):
    p = (p or '').upper()
    m = re.match(r'^(?:PL|FL|FB|BL|PLT|FLT|PLATE|BPL|FPL|FLAT)\s*(\d+(?:\.\d+)?)\s*[X\*x]\s*(\d+(?:\.\d+)?)$', p)
    if m: return 'PLATE a*b, a>b' if float(m.group(1)) > float(m.group(2)) else 'PLATE a*b, a<=b'
    for k, rx in (('ANGLE', r'^L\d'), ('CHANNEL', r'^(C|MC|\[|U)\d'), ('W/I', r'^(W|HP|S|M|I|HE|IPE)\d'), ('HSS/TUBE', r'^(HSS|TS|RHS|SHS)'), ('PIPE', r'^(PIPE|D\d|PD)'), ('PLATE other', r'^(PL|FL|FB|F\.B|BL)'), ('ROUND', r'^(RB|ROD|R\.B)')):
        if re.match(rx, p): return k
    return 'other'
res = collections.defaultdict(collections.Counter); n = 0; ex = collections.defaultdict(list)
for pid in sorted(set(A) & set(B))[I0:I1]:
    te = tg.get(pid2g.get(pid))
    if te is None or pid not in byp: continue
    tv = verts(te)
    if tv is None or not len(tv): continue
    m = byp[pid]; x = m['x']; y = m['y']; z = np.cross(x, y); R = np.stack([x, y, z]); Tb = tv @ R.T
    errs = []
    for P_, e in (A[pid], B[pid]):
        v = verts(e) if e is not None else None
        if v is None or not len(v): errs.append(None); continue
        Vb = v @ R.T
        errs.append(float(max(np.abs(Vb.min(0) - Tb.min(0)).max(), np.abs(Vb.max(0) - Tb.max(0)).max())))
    if None in errs: continue
    f_ = fam(A[pid][0][1]); r = res[f_]; r['n'] += 1; r['A_within_1mm'] += errs[0] <= 1; r['B_within_1mm'] += errs[1] <= 1
    k = 'improved' if errs[1] < errs[0] - 0.5 else ('worsened' if errs[1] > errs[0] + 0.5 else 'same'); r[k] += 1
    if k == 'worsened' and len(ex[f_]) < 3: ex[f_].append((pid, A[pid][0][1], round(errs[0], 1), round(errs[1], 1)))
    n += 1
    if n >= NMAX: break
print(json.dumps({'chunk': [I0, I1], 'n': n, 'res': {k: dict(v) for k, v in res.items()}, 'ex': {k: v for k, v in ex.items()}, 'total_pairs': len(set(A) & set(B))}))
