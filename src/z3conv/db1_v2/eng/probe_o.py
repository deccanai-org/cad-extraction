import sys, collections, numpy as np, time, json
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
exec(open('probe_n.py').read().split("t = time.time(); db = Db2(data)")[0].replace("f = sys.argv[1]; flags = [int(x) for x in sys.argv[2].split(',')]", "f = sys.argv[1]; flags = [1, 4, 5]"))
import db1dec
L = json.load(open('src/layouts.json')); eng = sys.argv[2]
db = Db2(data); db.segment(); db.PLAUS_MAX = 1e10
cand = L[eng]['layout']
pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k'])); print('pts', [(p['stride'], p['k'], len(p['keys'])) for p in pts])
cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k'])); print('csys', [(c['stride'], c['k'], c['key'], len(c['keys'])) for c in cs])
lay = dict(cand); lay['pts'] = 0
db._member_run = db.bystride.get(lay['stride'])
t = time.time(); M = members(db, pts, cs, lay); print('members', len(M), round(time.time() - t), 's prof', sum(1 for m in M if m['prof']), 'axis', db1dec._axis_agreement(db, pts, lay, M))
seqc = collections.Counter(m['seq'] for m in M); print('unique seq', len(seqc), 'dups', sum(1 for v in seqc.values() if v > 1))
print('flag of member recs', collections.Counter(int(db.u8[m['off'] + 8]) for m in M).most_common(4))
print(collections.Counter(m['prof'] for m in M).most_common(15))
import pickle; pickle.dump([(m['seq'], m['prof'], m['O'], m['E'], m['L'], m['x'], m['y'], m['off'], int(db.u8[m['off'] + 8])) for m in M], open('m_31b6.pkl', 'wb'))
