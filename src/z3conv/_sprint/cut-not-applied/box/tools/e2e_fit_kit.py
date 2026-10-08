"""e2e_fit_kit.py DB1 IFC OUTDIR (env KIT2: compare kit KIT [run 0] with kit KIT2 [run 1], fittings on in both) : (eng fork's e2e_fit.py on a kit) decode + write IFC with the kit's writer, fittings on / off;
each written part's solid vs the Tekla IFC solid of the same part (GUID join): axis-aligned bbox in our part frame, max error"""
import sys, os, re, json, numpy as np, collections
KIT = os.environ['KIT']; sys.path.insert(0, KIT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db1step, guid2
import ifcopenshell, ifcopenshell.geom, ifcopenshell.guid as ig, ifcopenshell.util.placement as up
from db1dec import load
f, ifc, od = sys.argv[1:4]; os.makedirs(od, exist_ok=True)
data = load(f); eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
cat = json.load(open(f'{KIT}/tekla_profiles.json'))
L = json.load(open(f'{KIT}/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
outs = {}
KIT2 = os.environ.get('KIT2')
if KIT2:
    import subprocess, pickle
for on in ('1', '0'):
    os.environ['DB1_FITTINGS'] = on if not KIT2 else '1'
    o = f'{od}/fit{on}.ifc'
    if KIT2 and on == '1':
        code = ("import sys, json, os, pickle; sys.path.insert(0, %r); import db1step; L = json.load(open(%r)); VA = [v['layout'] for v in L.values() if v.get('layout')]; "
                "st = db1step.convert(%r, %r, json.load(open(%r)), (L.get(%r) or {}).get('layout'), VA, False); pickle.dump(st, open(%r, 'wb'))") % (KIT2, KIT2 + '/layouts.json', f, o, KIT2 + '/tekla_profiles.json', eng, o + '.pkl')
        subprocess.run([sys.executable, '-c', code], check=True); st = pickle.load(open(o + '.pkl', 'rb'))
    else:
        st = db1step.convert(f, o, cat, (L.get(eng) or {}).get('layout'), VA, False)
    outs[on] = (o, st)
    print('engine', eng, 'fittings', on, st.get('status'), 'written', st.get('written'), 'cuts_applied', st.get('cuts_applied'), 'fittings', st.get('fittings'), flush=True)
pl = outs['1'][1].get('parts_list') or []
gs = ifcopenshell.geom.settings(); gs.set(gs.USE_WORLD_COORDS, True)
def shape_bbox(e, R):
    try:
        sh = ifcopenshell.geom.create_shape(gs, e); V = np.array(sh.geometry.verts).reshape(-1, 3)
        if np.abs(V).max() < 1e5: V = V * 1000.0
        W = V @ R.T; return W.min(0), W.max(0)
    except Exception: return None
G = guid2.scan(data)
T = ifcopenshell.open(ifc)
def gid(e):
    tag = getattr(e, 'Tag', None) or ''
    if tag.startswith('ID'): return tag[2:38].upper()
    g_ = ig.expand(e.GlobalId).upper(); return '%s-%s-%s-%s-%s' % (g_[:8], g_[8:12], g_[12:16], g_[16:20], g_[20:])
TE = {gid(e): e for e in T.by_type('IfcElement') if e.Representation}
best = None; seqs = [p[0] for p in pl]
for off in (8, 16, 26, 24, 4, 10, 12, 20, 28, 32):
    k2g = {}
    for p, s in G:
        v = int.from_bytes(data[p - off:p - off + 4], 'little', signed=True); k2g.setdefault(v, s)
    n = sum(1 for q in seqs if k2g.get(q) in TE)
    if best is None or n > best[0]: best = (n, off, k2g)
k2g = best[2]; print('guid join', best[0], 'of', len(seqs), 'offset', best[1])
res = collections.Counter(); ERR = {}
for on in ('1', '0'):
    O = ifcopenshell.open(outs[on][0]); OG = {e.GlobalId: e for e in O.by_type('IfcElement')}
    for seq, prof, cat_, stt, how, guid, nc in (outs[on][1].get('parts_list') or []):
        if stt != 'written': continue
        te = TE.get(k2g.get(seq)); oe = OG.get(guid)
        if te is None or oe is None: continue
        Mw = np.array(up.get_local_placement(oe.ObjectPlacement)); R = Mw[:3, :3].T
        a = shape_bbox(oe, R); b = shape_bbox(te, R)
        if a is None or b is None: continue
        err = max(np.abs(a[0] - b[0]).max(), np.abs(a[1] - b[1]).max())
        res[(on, 'parts')] += 1; res[(on, 'bbox<=1mm')] += err <= 1.0
        ERR.setdefault(seq, {})[on] = (float(err), prof)
print({f'{k[0]}:{k[1]}': v for k, v in sorted(res.items())})
ch = collections.Counter(); worse = []; better = []
for q, d in ERR.items():
    if '0' in d and '1' in d:
        if d['1'][0] < d['0'][0] - 0.5: ch['improved'] += 1; better.append((q, d['1'][1], round(d['0'][0], 1), round(d['1'][0], 1)))
        elif d['1'][0] > d['0'][0] + 0.5: ch['worsened'] += 1; worse.append((q, d['1'][1], round(d['0'][0], 1), round(d['1'][0], 1)))
        else: ch['same'] += 1
print('per part, run 1 vs run 0:' if KIT2 else 'per part, fittings on vs off:', dict(ch), 'improved e.g.', better[:5], 'worsened e.g.', worse[:8])
json.dump(dict(res={f'{k[0]}:{k[1]}': int(v) for k, v in res.items()}, change=dict(ch), worse=[[int(a), b, c, d] for a, b, c, d in worse], better=[[int(a), b, c, d] for a, b, c, d in better[:50]],
               written=[outs['1'][1].get('written'), outs['0'][1].get('written')]), open(f'{od}/e2e.json', 'w'), default=str)
for on in ('1', '0'):
    try: os.remove(outs[on][0])
    except Exception: pass
