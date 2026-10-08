"""Try the approved 9.08 layout (and every approved variant) on a 9.21 DB1 through the kit's own decode + guards."""
import sys, os, json, time
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', os.environ.get('KIT', 'kit_snapshot')))
from db1step import convert
L = json.load(open(os.path.join(H, '..', 'kit_snapshot', 'layouts.json')))
V = [v['layout'] for v in L.values() if v.get('layout')]
cat = json.load(open(os.path.join(H, '..', 'kit_snapshot', 'tekla_profiles.json')))
f = sys.argv[1]; base = sys.argv[2] if len(sys.argv) > 2 else '9.08'; full = os.environ.get('FULL', '0') == '1'
out = sys.argv[3] if len(sys.argv) > 3 else '/tmp/try921.ifc'
t0 = time.time()
st = convert(f, out, cat, L[base]['layout'], V, allow_full=full)
pl = st.pop('parts_list', None)
print(json.dumps({k: v for k, v in st.items() if k not in ('trace',)}, default=str, indent=0)[:6000])
print('secs', round(time.time() - t0, 1))
if pl: json.dump(pl, open(out + '.parts.json', 'w'))
