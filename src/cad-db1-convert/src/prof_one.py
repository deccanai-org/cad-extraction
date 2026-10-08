import sys, json, time, faulthandler; sys.path.insert(0,'src')
faulthandler.dump_traceback_later(45, repeat=True, file=sys.stderr)
from db1step import convert
cat = json.load(open('catalog/tekla_profiles.json')); L = json.load(open('layouts.json'))
V = [v['layout'] for v in L.values() if v.get('layout')]
t0=time.time(); st = convert(sys.argv[1], '/tmp/prof_one.ifc', cat, L[sys.argv[2]]['layout'], V, allow_full=True)
print('DONE', round(time.time()-t0), st.get('status'), st.get('members'), st.get('written'), st.get('axis_agreement'))
