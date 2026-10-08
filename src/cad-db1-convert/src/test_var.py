import sys, json, time
sys.path.insert(0, '/opt/db1v2/src3')
from db1step import convert
cat = json.load(open('/opt/db1v2/tekla_profiles.json'))
L = json.load(open('/opt/db1v2/layouts.json'))
variants = [v['layout'] for v in L.values() if v.get('layout')]
t = time.time()
st = convert(sys.argv[1], '/opt/db1v2/var.ifc', cat, L['8.07']['layout'], variants)
print(round(time.time() - t, 1), 's', {k: v for k, v in st.items() if k not in ('layout', 'unresolved_top')})
print('layout', {k: st.get('layout', {}).get(k) for k in ('fast', 'semi', 'csys', 'csys_key', 'attr', 'attr_stride', 'prof_off', 'rest_ref', 'rest_stride', 'rest_off', 'poly_field', 'poly_stride', 'tried')})
print('unresolved', (st.get('unresolved_top') or [])[:12])
