"""hot_cmp.py ID... : per-part check against the model folder's Tekla 'Hot_Rolled_list' / 'Hot_Fittings_list' reports, which print per
mark the NET weight of one part ('Weight') and the GROSS total ('Tot.Wt' = qty x gross): a part whose Tekla net is below its gross
has cuts. Our parts are matched by profile + length (|L - Tekla length| <= 1 mm, same profile string); per matched part:
Tekla net / gross vs our STEP weight after / before the patch."""
import sys, os, re, json, gzip, glob, collections
RHO = 7.85e-6
NUM = re.compile(r'^-?\d+(\.\d+)?$')
def parse_hot(path):
    rows = []
    for l in open(path, 'rb').read().decode('latin-1').replace('\r', '').split('\n'):
        t = l.split()
        if len(t) < 8 or not all(NUM.match(x) for x in t[-5:]): continue
        if not re.match(r'^\d+$', t[-5]): continue
        qty = int(t[-5]); length = float(t[-4]); net = float(t[-2]); tot = float(t[-1]); grade = t[-6]; size = ' '.join(t[1:-6])
        if not size or qty <= 0: continue
        rows.append(dict(mark=t[0], prof=size.replace('\xd8', 'Ø'), qty=qty, length=length, net=net, gross=tot / qty))
    return rows
def load(d):
    pl = json.load(gzip.open(os.path.join(d, 'convert.json.parts.json.gz'), 'rt'))
    vol = collections.Counter()
    for l in gzip.open(os.path.join(d, 'step_parts.jsonl.gz'), 'rt'):
        s = json.loads(l)
        if s.get('pid') and s.get('volume') is not None: vol[s['pid']] += s['volume']
    return {pid: (prof, nc, vol.get(gid)) for pid, prof, cat, st, how, gid, nc in pl if st == 'written' and gid}
def dec_len(id_, kit):
    p = f'dec/{kit}/{id_}.json'
    if not os.path.exists(p): return {}
    d = json.load(open(p)); return {x[0]: x[5] for x in d['parts']}
tot = collections.Counter()
for ID in sys.argv[1:]:
    rows = []
    for f in sorted(glob.glob(f'reports/{ID}/Hot_*list*.xsr')): rows += parse_hot(f)
    if not rows or not os.path.exists(os.environ.get('PIPE_B', 'pipes/kitp') + f'/{ID}/step_parts.jsonl.gz') or not os.path.exists(os.environ.get('PIPE_A', 'pipes/kit') + f'/{ID}/step_parts.jsonl.gz'): continue
    A, B = load(os.environ.get('PIPE_A', 'pipes/kit') + f'/{ID}'), load(os.environ.get('PIPE_B', 'pipes/kitp') + f'/{ID}')
    LA = dec_len(ID, 'before'); LB = dec_len(ID, 'after')
    byk = collections.defaultdict(list)
    for pid, (prof, nc, v) in B.items():
        if pid in LB and v: byk[prof].append((LB[pid], pid, nc, v))
    cutrows = [r for r in rows if r['gross'] - r['net'] > max(0.15, 0.015 * r['gross'])]
    res = collections.Counter(); ex = []
    errA = errB = 0.0; nm = 0
    for r in rows:
        cand = [c for c in byk.get(r['prof'], []) if abs(c[0] - r['length']) <= 1.0]
        if not cand: res['unmatched'] += 1; continue
        nm += 1
        aft = sum(c[3] for c in cand) / len(cand) * RHO
        bef = [A[c[1]][2] * RHO for c in cand if c[1] in A and A[c[1]][2]]
        befv = sum(bef) / len(bef) if bef else None
        errB += abs(aft - r['net'])
        if befv is not None: errA += abs(befv - r['net'])
        if r in cutrows:
            res['tekla_cut_rows'] += 1
            ok_after = abs(aft - r['net']) <= max(0.1, 0.02 * r['net'])
            ok_before = befv is not None and abs(befv - r['net']) <= max(0.1, 0.02 * r['net'])
            res['cut_rows_net_ok_after'] += ok_after; res['cut_rows_net_ok_before'] += ok_before
            if len(ex) < 14: ex.append((r['mark'], r['prof'], r['length'], 'tekla net', r['net'], 'gross', round(r['gross'], 2), 'ours before', round(befv, 2) if befv else None, 'after', round(aft, 2), 'n', len(cand)))
    print('==', ID, 'report rows', len(rows), 'matched', nm, dict(res), '| sum |ours - Tekla net| kg: before %.1f after %.1f' % (errA, errB))
    for e in ex: print('     ', e)
    for k, v in res.items(): tot[k] += v
    tot['abs_err_before'] += errA; tot['abs_err_after'] += errB; tot['matched'] += nm
print('TOTAL', dict(tot))
