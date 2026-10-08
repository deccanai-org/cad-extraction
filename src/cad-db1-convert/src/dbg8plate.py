import sys, json, re, pickle, collections, os, numpy as np
sys.path.insert(0, '/opt/db1v2/src3')
from db1dec import *
import plate_truth
tag = sys.argv[1]
b = f'/opt/db1v2/pairs/{tag}.ifc'
if not os.path.exists(b + '.plates.pkl'): pickle.dump(plate_truth.plates(b), open(b + '.plates.pkl', 'wb'))
PL = [p for p in pickle.load(open(b + '.plates.pkl', 'rb')) if p['cls'] == 'IfcPlate']
L = json.load(open('/opt/db1v2/layouts.json')); variants = [v['layout'] for v in L.values() if v.get('layout')]
db, pts, cs, lay = decode(f'/opt/db1v2/pairs/{tag}.db1', L['8.07']['layout'], variants, False)
M = members(db, pts, cs, lay)
cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
print(tag, 'IfcPlate', len(PL), 'contour members', len(cp), 'layout fast', lay.get('fast'), 'semi', lay.get('semi'))
# shift from member matching (IFC may be offset)
Ms = [m for m in M if m['prof'] and not m['cut']]
A = np.array([p['pts'][0] for p in PL]) if PL else np.zeros((0, 3))
shown = 0; stat = collections.Counter()
for p in PL[:200]:
    V = p['pts'][:-1]; mid = V + p['n'] * p['t'] / 2
    dmin = [(np.min(np.linalg.norm(mid - m['O'], axis=1)), m) for m in cp]
    if not dmin: break
    d, m = min(dmin, key=lambda x: x[0])
    stat['member_at_vertex' if d < 1 else 'no_member_at_vertex'] += 1
    if d < 1 and shown < 3:
        shown += 1
        loc = [((q - m['O']) @ m['x'], (q - m['O']) @ m['y']) for q in mid]
        print('plate', p['prof'], 'n', len(V), 'L', round(m['L'], 2), 'local uv', [(round(a, 1), round(c, 1)) for a, c in loc])
        # search the whole file for the non-trivial local coords as float32 and float64
        for (u, v) in loc[2:4]:
            for val in (u, v):
                if abs(val) < 1: continue
                f32 = np.frombuffer(db.b, np.uint8)
                hits32 = [mm.start() for mm in re.finditer(re.escape(np.float32(val).tobytes()), db.b)][:5]
                print('    value', round(val, 2), 'f32 hits', hits32)
print(stat)
