"""end-to-end: decode + write IFC with the patched writer (fittings on / off), then compare each fitted part's solid with the
Tekla IFC solid of the same part (GUID join): axis-aligned bbox in the part's own frame, per-axis error"""
import sys, os, json, numpy as np, collections, subprocess
sys.path.insert(0, 'step'); sys.path.insert(0, 'src'); sys.path.insert(0, '.'); sys.path.append('/Users/dhiren/Downloads/Deccan/z3conv/db1')
import db1step, guid2
import ifcopenshell, ifcopenshell.geom, ifcopenshell.guid as ig
f, ifc, eng = sys.argv[1:4]
cat = json.load(open('/Users/dhiren/Downloads/Deccan/z3conv/db1/tekla_profiles.json'))
L = json.load(open('src/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
outs = {}
for on in ('1', '0'):
    os.environ['DB1_FITTINGS'] = on
    o = f'fit/e2e_{os.path.basename(f)}_{on}.ifc'
    st = db1step.convert(f, o, cat, L[eng]['layout'], VA, False)
    outs[on] = (o, st)
    print('fittings', on, st.get('status'), 'written', st.get('written'), st.get('fittings'), flush=True)
pl = outs['1'][1].get('parts_list') or []
gs = ifcopenshell.geom.settings(); gs.set(gs.USE_WORLD_COORDS, True)
def shape_bbox(e, R):
    try:
        sh = ifcopenshell.geom.create_shape(gs, e); V = np.array(sh.geometry.verts).reshape(-1, 3)
        if np.abs(V).max() < 1e5: V = V * 1000.0
        W = V @ R.T; return W.min(0), W.max(0)
    except Exception: return None
from db1dec import load
data = load(f); G = guid2.scan(data)
T = ifcopenshell.open(ifc)
def gid(e):
    tag = getattr(e, 'Tag', None) or ''
    if tag.startswith('ID'): return tag[2:38].upper()
    g_ = ig.expand(e.GlobalId).upper(); return '%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
TE = {gid(e): e for e in T.by_type('IfcElement') if e.Representation}
best = None
seqs = [p[0] for p in pl]
for off in (8, 16, 26, 24, 4, 10, 12, 20, 28, 32):
    k2g = {}
    for p, s in G:
        v = int.from_bytes(data[p - off:p - off + 4], 'little', signed=True); k2g.setdefault(v, s)
    n = sum(1 for q in seqs if k2g.get(q) in TE)
    if best is None or n > best[0]: best = (n, off, k2g)
k2g = best[2]
res = collections.Counter(); ex = []; ERR = {}
for on in ('1', '0'):
    O = ifcopenshell.open(outs[on][0]); OG = {e.GlobalId: e for e in O.by_type('IfcElement')}
    plo = outs[on][1].get('parts_list') or []
    fitted = set(outs['1'][1].get('fitted_seqs', []))
    for seq, prof, cat_, stt, how, guid, nc in plo:
        if stt != 'written': continue
        te = TE.get(k2g.get(seq)); oe = OG.get(guid)
        if te is None or oe is None: continue
        if not (oe.Representation.Representations[0].RepresentationType == 'CSG' or on == '0'): pass
        # frame: our element placement axes
        import ifcopenshell.util.placement as up
        Mw = np.array(up.get_local_placement(oe.ObjectPlacement)); R = Mw[:3, :3].T
        a = shape_bbox(oe, R); b = shape_bbox(te, R)
        if a is None or b is None: continue
        err = max(np.abs(a[0] - b[0]).max(), np.abs(a[1] - b[1]).max())
        res[(on, 'parts')] += 1; res[(on, 'bbox<=1mm')] += err <= 1.0
        ERR.setdefault(seq, {})[on] = float(err)
        if on == '1' and err > 1.0 and len(ex) < 6: ex.append((seq, prof, round(float(err), 1)))
print({k: v for k, v in sorted(res.items())}); print('worst with fittings on', ex)

ch = collections.Counter(); worse = []
for q, d in ERR.items():
    if '0' in d and '1' in d:
        if d['1'] < d['0'] - 0.5: ch['improved'] += 1
        elif d['1'] > d['0'] + 0.5: ch['worsened'] += 1; worse.append((q, round(d['0'], 1), round(d['1'], 1)))
        else: ch['same'] += 1
print('per part with fittings vs without:', dict(ch), 'worsened examples', worse[:8])
