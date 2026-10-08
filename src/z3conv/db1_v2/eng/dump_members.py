"""dump_members.py SRCDIR DB1 ENGINE OUT.pkl -> decoded members (seq, prof, O, E, cut) + layout"""
import sys, json, pickle, time, re
src, f, eng, out = sys.argv[1:5]
sys.path.insert(0, src)
import db1dec
from db1dec import decode, members, load
L = json.load(open(src + '/layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
t = time.time(); data = load(f)
db, pts, cs, lay = decode(data, (L.get(eng) or {}).get('layout'), VA, len(data) < 20_000_000)
M = members(db, pts, cs, lay) if lay and lay.get('csys') is not None else []
polys = {}
for m in M:
    if m['prof'] and db1dec.PLATE1_RE.match(m['prof']) and lay.get('poly_stride'):
        polys[m['seq']] = db.polygon(lay, m)
pickle.dump(dict(lay={k: v for k, v in (lay or {}).items() if k != 'tried'}, M=[(m['seq'], m['prof'], m['O'].tolist(), m['E'].tolist(), m['y'].tolist(), m['cut']) for m in M], polys=polys, sec=time.time() - t), open(out, 'wb'))
print(f, len(M), round(time.time() - t, 1))
