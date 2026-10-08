"""local test: DB1 -> IFC (v2 db1step) -> stats json.  run_conv.py DB1 OUT_PREFIX"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db1step
db1, outp = sys.argv[1:3]
L = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layouts.json')))
import re, gzip, zlib
raw = open(db1, 'rb').read(1 << 16); d = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
eng = re.search(rb'(\d+\.\d+)', d[:16]).group(1).decode()
cat = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tekla_profiles.json')))
t = time.time()
st = db1step.convert(db1, outp + '.ifc', cat, (L.get(eng) or {}).get('layout'), [v['layout'] for v in L.values() if v.get('layout')], allow_full=False)
if st.get('status') == 'deferred_layout':
    st = db1step.convert(db1, outp + '.ifc', cat, (L.get(eng) or {}).get('layout'), [v['layout'] for v in L.values() if v.get('layout')], allow_full=True); st['full_discovery'] = True
pl = st.pop('parts_list', None)
json.dump(st, open(outp + '.json', 'w'), indent=1, default=str)
if pl is not None: json.dump(pl, open(outp + '.parts.json', 'w'))
print(json.dumps({k: st.get(k) for k in ('status', 'members', 'written', 'sources', 'skipped', 'secs')}, default=str))
print(json.dumps(st.get('bolt_stats'), default=str)[:3000])
