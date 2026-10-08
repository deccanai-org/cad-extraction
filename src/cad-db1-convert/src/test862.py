import sys, json, time
sys.path.insert(0, '/opt/db1v2/src3')
from db1step import convert
cat = json.load(open('/opt/db1v2/tekla_profiles.json')); L = json.load(open('/opt/db1v2/layouts.json')); V = [v['layout'] for v in L.values() if v.get('layout')]
t = time.time(); st = convert(sys.argv[1], '/opt/db1v2/t862.ifc', cat, L['8.62']['layout'], V)
lay = st['layout']
print(round(time.time() - t), 's', {k: st.get(k) for k in ('members', 'written', 'skipped', 'status', 'y_vertical_frac')}, {k: lay.get(k) for k in ('fast', 'poly_field', 'poly_ub', 'poly_vb', 'poly_cap', 'poly_frac')})
print(st.get('unresolved_top', [])[:12])
