"""rep_len.py ID [KIT] : the model folder's Tekla Hot_Rolled / Hot_Fittings lists print per mark the part LENGTH Tekla reports
(after fittings). Our decoded parts (profile, length) before / after the P13 fittings are matched to the report rows (same profile,
|length difference| <= 1 mm, report quantities consumed): how many report parts find a part of ours with Tekla's length."""
import sys, os, re, json, glob, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; ID = sys.argv[1]; KIT = sys.argv[2] if len(sys.argv) > 2 else W + '/kitnp4'
sys.path.insert(0, KIT); sys.path.insert(0, W + '/tools')
import db1old, db1step
from db1dec import load
from hot_cmp import parse_hot
src = glob.glob(f'{W}/src/{ID}*.db1')[0]; data = load(src); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
cat = json.load(open(f'{KIT}/tekla_profiles.json'))
FIT = db1old.FIT
rows = []
for f in sorted(glob.glob(f'{W}/reports/{ID[:4]}/Hot_*list*.xsr')) + sorted(glob.glob(f'{W}/reports/{ID}/Hot_*list*.xsr')):
    rows += [dict(r, file=os.path.basename(f)) for r in parse_hot(f)]
print('==', ID, eng, 'parts', len(M), 'report rows', len(rows), 'report parts', sum(r['qty'] for r in rows), 'fittings', info.get('fittings_decoded'))
def norm(p): return re.sub(r'\s+', '', (p or '').upper().replace('\xd8', 'D').replace('Ø', 'D'))
ours = {'before': [], 'after': []}; fitted = {}
for m in M:
    if m['cut'] or m['bolt']: continue
    fl = FIT.get(9, {}).get(m['pid'], []); lc = FIT.get(12, {}).get(m['pid'], [])
    L0 = m['L']; L1 = L0; kind = 'nofit'
    if fl or lc:
        k_, v_, _ = db1step.section_for(m['prof'], cat)
        mm, hs, nt = db1step.fit_old_plan(m, fl, lc, k_, v_)
        obl = nt.get('oblique', 0) > 0
        L1 = mm['L'] if not obl else None; kind = 'oblique' if obl else ('perp' if fl else 'linecut_only')
        fitted[m['pid']] = (m['prof'], round(L0, 1), None if L1 is None else round(L1, 1), kind, dict(nt))
    ours['before'].append((norm(m['prof']), L0, kind)); ours['after'].append((norm(m['prof']), L1 if L1 is not None else L0, kind))
for lab in ('before', 'after'):
    pool = collections.defaultdict(list)
    for p, L, k in ours[lab]: pool[p].append([L, k, 1])
    got = collections.Counter(); miss_ex = []
    for r in rows:
        p = norm(r['prof'])
        for _ in range(r['qty']):
            c = [x for x in pool.get(p, []) if x[2] and abs(x[0] - r['length']) <= 1.0]
            if c: c[0][2] = 0; got['matched'] += 1; got['matched_' + c[0][1]] += 1
            else: got['unmatched'] += 1
    print(f'   {lab:6s}: report parts matched by profile + length (<= 1 mm):', dict(got))
pf = collections.Counter(v[3] for v in fitted.values())
print('   fitted parts', len(fitted), dict(pf))
for pid, v in list(fitted.items())[:25]:
    p = norm(v[0]); cand = sorted({r['length'] for r in rows if norm(r['prof']) == p}, key=lambda x: abs(x - (v[2] or v[1])))[:3]
    print('     ', pid, v, 'nearest report lengths', cand)
