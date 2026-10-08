import sys, json, time, glob; sys.path.insert(0, 'src')
from db1step import convert
cat = json.load(open('catalog/tekla_profiles.json')); L = json.load(open('layouts.json'))
V = [v['layout'] for v in L.values() if v.get('layout')]
near = {'9.08': '8.95', '7.98': '8.07', '8.44': '8.53', '8.37': '8.07', '7.62': '7.64', '8.74': '8.65', '8.30': '8.07', '7.81': '7.82', '7.52': '7.64', '7.61': '7.64'}
print('layouts.json entries for unapproved:', {e: (bool(L.get(e, {}).get('layout')), L.get(e, {}).get('approved')) for e in near})
for f in sorted(glob.glob('pairs/data/un_*.db1')):
    eng = f.split('_')[1]; base = (L.get(eng) or {}).get('layout') or L[near[eng]]['layout']
    t0 = time.time(); st = convert(f, f.replace('.db1', '_t.ifc'), cat, base, V, allow_full=True)
    lay = st.get('layout') or {}
    mode = 'fast' if lay.get('fast') else ('semi' if lay.get('semi') else ('old' if lay.get('format') == 'old' else 'full'))
    print(f.split('/')[-1], round(time.time() - t0), 's', st.get('status'), 'members', st.get('members'), 'written', st.get('written'),
          'axis', st.get('axis_agreement'), 'yv', st.get('y_vertical_frac'), mode, 'csys', lay.get('csys'), lay.get('csys_key'),
          'attr', lay.get('attr_stride'), 'prof_score', lay.get('prof_score'), 'poly', lay.get('poly_stride'), lay.get('poly_field2'),
          'src', st.get('sources'), 'skip', st.get('skipped'), flush=True)
