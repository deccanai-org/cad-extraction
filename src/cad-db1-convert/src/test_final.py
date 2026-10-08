import sys, json, time
sys.path.insert(0, '/opt/db1v2/src3')
from db1step import convert
cat = json.load(open('/opt/db1v2/tekla_profiles.json')); L = json.load(open('/opt/db1v2/layouts.json')); V = [v['layout'] for v in L.values() if v.get('layout')]
for path, eng in (('/opt/db1v2/pairs/8.53_0575f7270f.db1', '8.53'), ('/opt/db1v2/pairs/var807.db1', '8.07'), ('/opt/db1v2/pairs/f862.db1', '8.62')):
    t = time.time(); st = convert(path, '/opt/db1v2/tf.ifc', cat, L[eng]['layout'], V, allow_full=False)
    lay = st.get('layout') or {}
    print(path.split('/')[-1], round(time.time() - t), 's', {k: st.get(k) for k in ('members', 'written', 'status', 'cuts_applied', 'y_vertical_frac', 'skipped')}, 'fast', lay.get('fast'), 'semi', lay.get('semi'), 'csys', lay.get('csys'), lay.get('csys_key'), 'poly', lay.get('poly_field'))
