"""9.21 vs 9.08: stride histogram, fast-path decode with the 9.08 layout, then with attr record variants; guards on the result."""
import sys, os, json, time, re, collections, numpy as np
H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, '..', 'kit_snapshot'))
import db1dec
from db1dec import *
L = json.load(open(os.path.join(H, '..', 'kit_snapshot', 'layouts.json')))
f = sys.argv[1]
t0 = time.time(); data = load(f); db = Db(data); db.segment()
print(os.path.basename(f)[:40], 'len', len(data), data[:12], 'segment', round(time.time() - t0, 1), 's')
c = collections.Counter({s: len(r) for s, r in db.bystride.items()})
print('top strides', c.most_common(25))
def attempt(cand, tag):
    t = time.time()
    pts = db.find_points(fixed=(cand['pts_stride'], cand['pts_k']))
    if not pts: print(tag, 'no points'); return None
    cs = db.find_csys(only=(cand['csys_stride'], cand['csys_k']))
    lay = dict(cand); lay['pts'] = 0
    recs = db.bystride.get(lay['stride'])
    if recs is None: print(tag, 'no member stride', lay['stride']); return None
    db._member_run = recs
    M = members(db, pts, cs, lay)
    ag = db1dec._axis_agreement(db, pts, lay, M) if M else None
    withp = sum(1 for m in M if m['prof'])
    profs = collections.Counter(m['prof'] for m in M if m['prof'])
    print(tag, 'members', len(M), 'with profile', withp, 'accept', db1dec._accept(db, lay, M), 'axis_agreement', ag, 'secs', round(time.time() - t, 1))
    print('   top profiles', profs.most_common(12))
    if M:
        noprof = [m for m in M if not m['prof']]
        st = collections.Counter(int(x) for x in db.lookup_stride([m['attr'] for m in noprof[:3000]])) if noprof else {}
        print('   attr strides of profile-less members', collections.Counter(st).most_common(5) if st else None)
    return M, lay, pts, cs
base = dict(L['9.08']['layout'])
r = attempt(base, '9.08 layout')
for S, po, rr in ((381, 125, 189), (345, 85, 149), (349, 85, 149), (353, 85, 149)):
    cand = dict(base); cand.update(attr_stride=S, prof_off=po, rest_ref=rr)
    attempt(cand, f'attr_stride={S} prof_off={po}')
