"""Convert a 9.21 DB1 through the kit's db1step.convert with the candidate 9.21 layout (patched/layouts.json); report guards,
profile-name rebuild paths (direct vs rest-record), contour-plate outlines, cut links."""
import sys, os, json, time, collections
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_patched'))
import db1dec
from db1step import convert
L = json.load(open(os.path.join(H, '..', 'patched', 'layouts.json')))
V = [v['layout'] for v in L.values() if v.get('layout')]
cat = json.load(open(os.path.join(H, '..', 'kit_snapshot', 'tekla_profiles.json')))
f, out = sys.argv[1], sys.argv[2]
t0 = time.time()
st = convert(f, out, cat, L['9.21']['layout'], V, allow_full=False)
pl = st.pop('parts_list', None)
lay = st.get('layout') or {}
print(json.dumps({k: v for k, v in st.items() if k not in ('trace', 'layout')}, default=str)[:3000])
print('layout', {k: lay.get(k) for k in ('fast', 'semi', 'attr_stride', 'prof_off', 'rest_ref', 'axis_agreement', 'poly_stride', 'poly_field', 'poly_frac', 'poly_ch', 'fast_members')})
print('secs', round(time.time() - t0, 1))
if pl:
    json.dump(pl, open(out + '.parts.json', 'w'))
    c = collections.Counter((r[2], r[3], r[4]) for r in pl); print('parts by (cat,status,how):', c.most_common(20))
