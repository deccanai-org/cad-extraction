"""dec_summary.py KITDIR DB1 OUT.json : old-engine decode summary (parts, cuts, type-11 links) with the kit's db1old"""
import sys, os, re, json, collections
KIT = sys.argv[1]; sys.path.insert(0, KIT)
import db1old, db1prof
from db1dec import load
data = load(sys.argv[2]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
out = {'engine': eng}
if eng < 7.5:
    M, info, cut_rel = db1old.read(data, eng)
    M = [m for m in M if not db1prof.is_null_record(m)]
    T = getattr(db1old, 'LAST', {}) or {}
    attrs = T.get('attrs') or {}
    parts = [[m['pid'], m['prof'], bool(m['cut']), bool(m['bolt']), m.get('obj_type', (attrs.get(m['attr']) or {}).get('obj_type')), round(m['L'], 1), m['mat'],
              m.get('axis_ok')] for m in M]
    out.update(info={k: v for k, v in info.items()}, parts=parts, cut_rel={str(k): v for k, v in cut_rel.items()})
json.dump(out, open(sys.argv[3], 'w'), default=str)
