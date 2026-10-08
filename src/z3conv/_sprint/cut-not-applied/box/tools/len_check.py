"""len_check.py ID DIR_A DIR_B PROFILE... : per profile, our parts' solid extent along the member axis (from the written IFC) and STEP
weight, before (A) / after (B), matched to the model folder's Tekla Hot_Rolled / Hot_Fittings rows (mark, qty, LENGTH, net weight):
how many report parts find one of our parts with Tekla's length (+-1.5 mm), and |our kg - Tekla net| on the matched ones"""
import sys, os, re, json, gzip, glob, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; ID, DA, DB = sys.argv[1:4]; PROFS = sys.argv[4:]
sys.path.insert(0, os.environ.get('KIT', W + '/kitnp7')); sys.path.insert(0, W + '/tools')
import db1old
from db1dec import load
import importlib.util as _iu
_sp = _iu.spec_from_file_location('hc', W + '/tools/hot_cmp.py'); _src = open(W + '/tools/hot_cmp.py').read().split('tot = collections.Counter()')[0]
_ns = {}; exec(compile(_src, 'hot_cmp', 'exec'), _ns); parse_hot = _ns['parse_hot']
import ifcopenshell, ifcopenshell.geom
RHO = 7.85e-6
data = load(glob.glob(f'{W}/src/{ID}*.db1')[0]); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng); byp = {m['pid']: m for m in M}
rows = []
for f in sorted(glob.glob(f'{W}/reports/{ID[:4]}/Hot_*list*.xsr')): rows += parse_hot(f)
def norm(p): return re.sub(r'\s+', '', (p or '').upper().replace('\xd8', 'D').replace('Ø', 'D'))
gs = ifcopenshell.geom.settings(); gs.set(gs.USE_WORLD_COORDS, True)
def ours(d):
    pl = json.load(gzip.open(f'{d}/convert.json.parts.json.gz', 'rt')); vol = collections.Counter()
    for l in gzip.open(f'{d}/step_parts.jsonl.gz', 'rt'):
        s = json.loads(l)
        if s.get('pid') and s.get('volume') is not None: vol[s['pid']] += s['volume']
    f = ifcopenshell.open(f'{d}/model.ifc'); out = []
    for pid, prof, c_, st, how, gid, nc in pl:
        if st != 'written' or not gid or norm(prof) not in PN or pid not in byp: continue
        try:
            V = np.array(ifcopenshell.geom.create_shape(gs, f.by_guid(gid)).geometry.verts).reshape(-1, 3)
            V = V * 1000.0 if np.abs(V).max() < 2e4 else V
        except Exception: continue
        t = V @ byp[pid]['x']; out.append((norm(prof), pid, float(t.max() - t.min()), vol.get(gid, 0) * RHO))
    return out
PN = {norm(p) for p in PROFS} if PROFS else {norm(r['prof']) for r in rows}
for _p in list(PN):
    if _p.endswith('.'): PN.add(_p)
for lab, d in (('before', DA), ('after', DB)):
    O = ours(d); pool = collections.defaultdict(list)
    for p, pid, ext, kg in O: pool[p].append([ext, kg, pid, 1])
    res = collections.defaultdict(collections.Counter); err = collections.defaultdict(float); n_ = collections.Counter()
    for r in rows:
        p = norm(r['prof'])
        if p not in PN: p = next((q for q in PN if p.endswith('.') and q.startswith(p.rstrip('.'))), p)
        if p not in PN: continue
        for _ in range(r['qty']):
            c = sorted([x for x in pool[p] if x[3] and abs(x[0] - r['length']) <= 1.5], key=lambda x: abs(x[0] - r['length']))
            res[p]['report_parts'] += 1
            if c:
                c[0][3] = 0; res[p]['matched_by_length'] += 1; err[p] += abs(c[0][1] - r['net']); n_[p] += 1
                if os.environ.get('SHOW') and norm(os.environ['SHOW']) == p:
                    print('   ', lab, p, 'pid', c[0][2], 'ext %.1f' % c[0][0], 'kg %.2f' % c[0][1], '| report', r['mark'], r['length'], 'net', r['net'], 'gross %.2f' % r['gross'])
    if PROFS or os.environ.get('PERPROF'):
        for p in sorted(PN, key=lambda q: -err[q]):
            if not res[p]: continue
            print(f'{lab:6s} {p:16s} ours {len(pool[p]):3d} parts', dict(res[p]), '| sum |kg - Tekla net| on matched %.1f kg (n %d)' % (err[p], n_[p]))
    tr = sum(v['report_parts'] for v in res.values()); tm = sum(v['matched_by_length'] for v in res.values())
    print(f'{lab:6s} ALL PROFILES: report parts {tr}, matched by profile + length {tm}, sum |kg - Tekla net| on matched %.1f kg (mean %.3f kg/part)' % (sum(err.values()), sum(err.values()) / max(1, sum(n_.values()))))
