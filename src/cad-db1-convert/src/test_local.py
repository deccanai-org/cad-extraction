import sys, json, time
sys.path.insert(0, 'src')
from db1step import convert
cat = json.load(open('catalog/tekla_profiles.json')); L = json.load(open('layouts.json')); V = [v['layout'] for v in L.values() if v.get('layout')]
tests = sys.argv[1:] or ['8.53_0575f7270f:8.53', '8.07_211b33df06:8.07', '7.82_c73731fe0d:7.82', '7.82_4f7fa9df65:7.82', 's807:8.07', 'w807:8.07']
for t in tests:
    name, eng = t.split(':')
    t0 = time.time(); st = convert(f'pairs/data/{name}.db1', f'pairs/data/{name}_t.ifc', cat, L[eng]['layout'], V, allow_full=False)
    lay = st.get('layout') or {}
    print(name, round(time.time() - t0), 's', {k: st.get(k) for k in ('members', 'written', 'status', 'cuts_applied', 'y_vertical_frac', 'sources', 'skipped')},
          'poly', {k: lay.get(k) for k in ('poly_field', 'poly_stride', 'poly_field2', 'poly_stride2', 'poly_ub', 'poly_vb', 'poly_cap', 'poly_frac')}, flush=True)
