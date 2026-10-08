#!/usr/bin/env python3
"""census_cmp.py ROWS.json OUT.jsonl --jobs N : per model: source + the LIVE step_parts the row is graded on; kit census v2
and proposed census v3 on the source; grade_join of each with the same STEP parts -> outside counts and the parts whose
verdict changes (v2 in-band -> v3 outside = possible grader regression; v2 outside -> v3 in/dropped = what v3 hides)."""
import sys, os, json, gzip, subprocess, argparse, threading, statistics, collections
from concurrent.futures import ThreadPoolExecutor
import boto3
ap = argparse.ArgumentParser(); ap.add_argument('rows'); ap.add_argument('out'); ap.add_argument('--jobs', type=int, default=4)
a = ap.parse_args()
W = '/work/agentwork/ifc-volume-residue-review'
sys.path.insert(0, f'{W}/pkg/kit2')
import grade_join as G
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
s3 = boto3.client('s3', region_name='ap-south-1')
rows = json.load(open(a.rows))
lock = threading.Lock()
os.makedirs(f'{W}/cin', exist_ok=True)
done = set()
if os.path.exists(a.out):
    for l in open(a.out):
        try: done.add(json.loads(l)['id'])
        except Exception: pass


def step_parts_key(o):
    sk = o.get('step_key') or ''
    i = o['id']
    if sk.startswith('cad-disk-extract/zenitude-data-3/conversions/ifc-step/'):
        base = sk.rsplit('/', 1)[1]
        suf = base[len(i):-len('.step')] if base.startswith(i) and base.endswith('.step') else ''
        return [f'{ST}/ifc/detail/{i}{suf}.step_parts.jsonl.gz']
    return [f'{ST}/grade/detail/ifc-{i}.step_parts.jsonl.gz', f'{ST}/ifc/detail/{i}.step_parts.jsonl.gz']


def verdict(p, s):
    v = s.get('volume'); e = G.expected_volume(p)
    if not v or not e or e <= 0 or (s.get('solids') or 0) == 0:
        return None, None
    r = v / e
    if abs(r - 1) <= 0.05:
        return 'in', r
    if p.get('an') and p.get('pt') in G.CURVED:
        return ('in' if G.CURVED_BAND[0] <= r <= G.CURVED_BAND[1] else 'out'), r
    return 'out', r


def one(o):
    i = o['id']
    if i in done:
        return
    d = f'{W}/cin/{i[:16]}'; os.makedirs(d, exist_ok=True)
    res = {'id': i, 'class': o.get('class'), 'reused': o.get('reused')}
    try:
        sp = None
        for k in step_parts_key(o):
            try:
                s3.download_file(B, k, f'{d}/step_parts.jsonl.gz'); sp = k; break
            except Exception:
                continue
        if not sp:
            res['error'] = 'no step_parts'; raise StopIteration
        res['step_parts_key'] = sp
        s3.download_file(B, o['input_key'], f'{d}/in.bin')
        for v, cen in (('v2', 'ifc_census_v2.py'), ('v3', 'ifc_census_v3.py')):
            r = subprocess.run(['/opt/conv/env/bin/python', f'{W}/pkg/{cen}', f'{d}/in.bin', f'{d}/c{v}.json', '--parts', f'{d}/p{v}.jsonl.gz'],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode:
                res['error'] = f'census {v}: ' + r.stderr[-300:]; raise StopIteration
        step = G.load(f'{d}/step_parts.jsonl.gz')
        p2, p3 = G.load(f'{d}/pv2.jsonl.gz'), G.load(f'{d}/pv3.jsonl.gz')
        c3 = json.load(open(f'{d}/cv3.json'))
        res['apps'] = c3.get('applications'); res['rebased'] = c3.get('quantities_rebased')
        j2, j3 = G.join(p2, step), G.join(p3, step)
        res['mode'] = j2['mode']
        for v, j in (('v2', j2), ('v3', j3)):
            vv = j['volume']; res[v] = [vv['outside_5pct'] + vv['outside_curved_gross'], vv['checked']]
        # per-part verdict changes (gid mode only; name mode pairs differently per census)
        if j2['mode'] == 'gid':
            bypid = {}
            for s in step:
                if s.get('pid') and ((s.get('solids') or 0) > 0 or (s.get('faces') or 0) > 0):
                    bypid.setdefault(s['pid'], s)
            by2 = {p['gid']: p for p in p2 if p.get('gid')}
            newout = []; hidden = []; rb = collections.defaultdict(list); newan_in = newan_out = 0
            for p in p3:
                s = bypid.get(p.get('gid')); q2 = by2.get(p.get('gid'))
                if s is None or q2 is None:
                    continue
                a2, r2 = verdict(q2, s); a3, r3 = verdict(p, s)
                if p.get('an') and not q2.get('an') and a3:
                    newan_in += a3 == 'in'; newan_out += a3 == 'out'
                if p.get('qx') and s.get('volume') and p.get('q0'):
                    rb[p['qx']].append(s['volume'] / p['q0'])
                if a3 == 'out' and a2 != 'out':
                    newout.append([round(r3, 4), round(r2, 4) if r2 else None, p['gid'], p['cls'], p.get('name'), p.get('pt') or p.get('qk'), p.get('qx'), (s.get('desc') or '')[-60:]])
                if a2 == 'out' and a3 != 'out':
                    hidden.append([round(r2, 4), round(r3, 4) if r3 else None, p['gid'], p['cls'], p.get('name'), p.get('qx') or ('an' if p.get('an') else p.get('qk'))])
            res['v3_new_outside'] = len(newout); res['v3_new_outside_ex'] = sorted(newout, key=lambda x: -abs(x[0] - 1))[:15]
            res['v3_cleared'] = len(hidden); res['v3_cleared_ex'] = hidden[:10]
            res['v3_cleared_by'] = dict(collections.Counter(h[5] for h in hidden))
            res['new_an_in'] = newan_in; res['new_an_out'] = newan_out
            res['rebased_step_over_q0'] = {k: [len(v), round(min(v), 4), round(statistics.median(v), 4), round(max(v), 4),
                                               sum(1 for x in v if abs(x - 1) <= 0.05)] for k, v in rb.items()}
    except StopIteration:
        pass
    except Exception as e:
        res['error'] = f'{type(e).__name__}: {str(e)[:300]}'
    finally:
        subprocess.run(['rm', '-rf', d])
    with lock:
        with open(a.out, 'a') as fh:
            fh.write(json.dumps(res, default=str) + '\n')


with ThreadPoolExecutor(a.jobs) as ex:
    list(ex.map(one, rows))
print('CENSUS CMP DONE')
