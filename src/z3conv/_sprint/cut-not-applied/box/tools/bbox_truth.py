"""bbox_truth.py NAME OURDIR [N] : per part, our IFC solid vs Tekla's own IFC solid of the same part (GUID join): bounding box of each
in OUR part frame (x along the member, y, z section axes) -> section-centre offset (dy, dz) and extents, by profile family"""
import sys, os, re, json, gzip, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME, D = sys.argv[1], sys.argv[2]; NMAX = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
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
O_ = ifcopenshell.open(os.path.join(D, 'model.ifc')); og = {e.GlobalId: e for e in O_.by_type('IfcElement')}
pl = json.load(gzip.open(os.path.join(D, 'convert.json.parts.json.gz'), 'rt'))
gs = ifcopenshell.geom.settings(); gs.set(gs.USE_WORLD_COORDS, True)
CEN = {}
def verts(e):
    try:
        sh = ifcopenshell.geom.create_shape(gs, e); V = np.array(sh.geometry.verts).reshape(-1, 3)
        V = V * 1000.0 if np.abs(V).max() < 2e4 else V
        F = np.array(sh.geometry.faces).reshape(-1, 3)
        if len(F):
            a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]; o = V.mean(0)
            vol = np.einsum('ij,ij->i', a - o, np.cross(b - o, c - o)) / 6.0
            CEN[id(e)] = ((((a + b + c + o) / 4.0) * vol[:, None]).sum(0) / vol.sum()) if abs(vol.sum()) > 1e-9 else None
        return V
    except Exception: return None
def fam(p):
    p = (p or '').upper()
    for k, rx in (('ANGLE', r'^L\d'), ('CHANNEL', r'^(C|MC|\[|U)\d'), ('W/I', r'^(W|HP|S|M|I|HE|IPE)\d'), ('HSS/TUBE', r'^(HSS|TS|RHS|SHS)'), ('PIPE', r'^(PIPE|D\d|PD)'), ('PLATE', r'^(PL|FL|FB|F\.B|BL)'), ('ROUND', r'^(RB|ROD|R\.B)')):
        if re.match(rx, p): return k
    return 'other'
res = collections.defaultdict(list); n = 0
for pid, prof, c_, st, how, gid, nc in pl:
    if st != 'written' or not gid or pid not in byp or nc: continue        # uncut parts only (cuts change the bbox)
    m = byp[pid]; te = tg.get(pid2g.get(pid)); oe = og.get(gid)
    if te is None or oe is None: continue
    a, b = verts(oe), verts(te)
    if a is None or b is None or not len(a) or not len(b): continue
    x = m['x']; y = m['y']; z = np.cross(x, y); R = np.stack([x, y, z])
    A, B = a @ R.T, b @ R.T
    ca, cb = (A.min(0) + A.max(0)) / 2, (B.min(0) + B.max(0)) / 2; ea, eb = A.max(0) - A.min(0), B.max(0) - B.min(0)
    cA, cB = CEN.get(id(oe)), CEN.get(id(te))
    dcen = np.round((cB - cA) @ R.T, 1) if cA is not None and cB is not None else np.array([np.nan] * 3)
    res[fam(prof)].append((pid, prof, np.round(cb - ca, 1), np.round(ea, 1), np.round(eb, 1), dcen))
    n += 1
    if n >= NMAX: break
print('==', NAME, eng, 'guid offset', best, 'compared uncut parts', n)
for k, v in sorted(res.items()):
    d = np.array([r[2] for r in v]); de = np.array([np.abs(r[3] - r[4]) for r in v])
    ok = int(((np.abs(d) <= 1.0).all(1) & (de <= 1.0).all(1)).sum())
    dc = np.array([r[5] for r in v]); okc = int((np.abs(dc[:, 1:]) <= 1.0).all(1).sum())
    print('  %-9s n %5d  bbox centre and size within 1 mm: %5d | volume centroid (y, z) within 1 mm: %5d | median |dy| %.1f |dz| %.1f |dx| %.1f | size diff median y %.1f z %.1f x %.1f' % (
        k, len(v), ok, okc, np.median(np.abs(d[:, 1])), np.median(np.abs(d[:, 2])), np.median(np.abs(d[:, 0])), np.median(de[:, 1]), np.median(de[:, 2]), np.median(de[:, 0])))
    bad = [r for r in v if not ((np.abs(r[2]) <= 1.0).all() and (np.abs(r[3] - r[4]) <= 1.0).all() and (np.abs(r[5][1:]) <= 1.0).all())]
    for r in bad[:4]: print('       ', r[0], r[1], 'centre offset (x,y,z)', r[2], 'our size', r[3], 'tekla size', r[4], 'centroid offset', r[5])
