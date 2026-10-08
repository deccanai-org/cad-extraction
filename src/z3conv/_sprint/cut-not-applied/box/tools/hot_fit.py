"""hot_fit.py ID DIR_NOFIT DIR_FIT [KIT] : parts with P13 fittings / line cuts vs the model folder's Tekla Hot_Rolled / Hot_Fittings
lists (per mark: LENGTH after fittings, NET weight of one part, gross). Our STEP volumes (x 7850 kg/m3) without / with fittings."""
import sys, os, re, json, gzip, glob, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; ID, DA, DB = sys.argv[1:4]; KIT = sys.argv[4] if len(sys.argv) > 4 else W + '/kitnp4'
sys.path.insert(0, KIT); sys.path.insert(0, W + '/tools')
import db1old, db1step
from db1dec import load
from hot_cmp import parse_hot
RHO = 7.85e-6
src = glob.glob(f'{W}/src/{ID}*.db1')[0]; data = load(src); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); FIT = db1old.FIT
cat = json.load(open(f'{KIT}/tekla_profiles.json'))
rows = []
for f in sorted(glob.glob(f'{W}/reports/{ID[:4]}/Hot_*list*.xsr')): rows += parse_hot(f)
def vols(d):
    pl = json.load(gzip.open(os.path.join(d, 'convert.json.parts.json.gz'), 'rt')); vol = collections.Counter()
    for l in gzip.open(os.path.join(d, 'step_parts.jsonl.gz'), 'rt'):
        s = json.loads(l)
        if s.get('pid') and s.get('volume') is not None: vol[s['pid']] += s['volume']
    return {pid: vol.get(gid) for pid, prof, c_, st, how, gid, nc in pl if st == 'written' and gid}
VA, VB = vols(DA), vols(DB)
def norm(p): return re.sub(r'\s+', '', (p or '').upper().replace('\xd8', 'D').replace('Ø', 'D'))
byprof = collections.defaultdict(list)
for r in rows: byprof[norm(r['prof'])].append(r)
res = collections.Counter(); ex = []; errA = errB = 0.0
for m in M:
    if m['cut'] or m['bolt']: continue
    fl = FIT.get(9, {}).get(m['pid'], []); lc = FIT.get(12, {}).get(m['pid'], [])
    if not fl and not lc: continue
    k_, v_, _ = db1step.section_for(m['prof'], cat)
    mm, hs, nt = db1step.fit_old_plan(m, fl, lc, k_, v_)
    # axis length to the fitting planes (no oblique extension margin)
    O, x, L = m['O'], m['x'], m['L']; mid = O + x * L / 2; t0, t1 = 0.0, L
    for P, n in fl:
        n_out = n if float((mid - P) @ n) < 0 else -n; c = float(n_out @ x)
        if abs(c) < 0.1: continue
        tp = float((P - O) @ n_out) / c
        if c > 0: t1 = tp
        else: t0 = tp
    La = t1 - t0
    a, b = VA.get(m['pid']), VB.get(m['pid'])
    if not a or not b: res['not_written'] += 1; continue
    cands = byprof.get(norm(m['prof']), [])
    best = min(cands, key=lambda r: min(abs(r['length'] - L), abs(r['length'] - La)), default=None)
    if best is None: res['profile_not_in_report'] += 1; continue
    dl = min(abs(best['length'] - L), abs(best['length'] - La))
    if dl > 1.0: res['no_report_length_within_1mm'] += 1; continue
    which = 'unfitted_L' if abs(best['length'] - L) <= abs(best['length'] - La) else 'fitted_axis_L'
    res['matched_by_' + which] += 1
    ka, kb = a * RHO, b * RHO
    ea, eb = abs(ka - best['net']), abs(kb - best['net']); errA += ea; errB += eb
    k = 'closer' if eb < ea - 0.05 else ('further' if eb > ea + 0.05 else 'same')
    res[k] += 1; res['kind_' + ('fit' if fl else 'linecut')] += 1
    if len(ex) < 40: ex.append((m['pid'], m['prof'], 'L %.1f axisL %.1f' % (L, La), 'report', best['mark'], best['length'], 'net', best['net'], 'gross', round(best['gross'], 2), 'ours nofit %.2f fit %.2f' % (ka, kb), k, 'fit' if fl else 'lc', dict(nt)))
print('==', ID, eng, dict(res), '| sum |ours - Tekla net| kg on matched fitted parts: nofit %.2f fit %.2f' % (errA, errB))
for e in ex: print('   ', e)
