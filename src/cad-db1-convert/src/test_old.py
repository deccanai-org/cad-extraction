import sys, json, time
sys.path.insert(0, '/opt/db1v2/src3')
from db1step import convert
cat = json.load(open('/opt/db1v2/tekla_profiles.json'))
for f in sys.argv[1:]:
    t = time.time(); st = convert(f, '/opt/db1v2/old_test.ifc', cat, None, [])
    print(f.split('/')[-1], round(time.time() - t), 's', {k: st.get(k) for k in ('members', 'written', 'skipped', 'cuts_applied', 'status', 'y_vertical_frac')}, st['layout'].get('cut_relations'))
