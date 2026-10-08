#!/bin/bash
# READ-ONLY IFC capacity check (lead 04:2xZ). Only S3 GET / LIST on the bim conversion state; writes nothing (stdout only).
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/ifc_capacity_check.sh 300
#  1. per box (fresh worker heartbeats of every pipeline, < 5 min): scratch total / free TB, IFC jobs running, IFC jobs >= 100 MB
#     running (the big_max count) and their sizes, IFC disk reservations, the IFC worker's gate, pipelines with a live worker
#  2. the open IFC queue (coordinator redo.json + jobs_reconvert.json, minus the jobs running now): size mix
#  3. scratch use of finished IFC jobs >= 100 MB (index step_bytes: the STEP output is most of a job's scratch): p50 / p95 / max
#  4. ap-southeast-1 boxes: is an IFC worker (assist loop) heartbeating; SDS2 primary jobs vs the assist start rule
#     (an SDS2 primary starts its assist loops when it has nothing to claim, or when a round starts nothing while it runs
#     < slots // 2 jobs and its CPU gate is open); last 'assist' lines of the SDS2 worker log
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, time, gzip, collections, statistics
import boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
BIG = 100 << 20; now = time.time()


def getb(k):
    try:
        return s3.get_object(Bucket=B, Key=k)['Body'].read()
    except Exception:
        return None


def getj(k):
    b = getb(k)
    return json.loads(b) if b else None


def lst(p):
    out = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=p):
        out += pg.get('Contents', [])
    return out


hb = collections.defaultdict(list)                     # host -> [(pipe, heartbeat)]
for p in ('ifc', 'sds2', 'db1', 'grade', 'final', 'verify', 'package'):
    objs = [o for o in lst(f'{ST}/{p}/hosts/') if now - o['LastModified'].timestamp() < 300]
    with ThreadPoolExecutor(32) as tp:
        for d, o in zip(tp.map(lambda o: getj(o['Key']), objs), objs):
            if d:
                d['_key'] = o['Key']; hb[d['host']].append((p, d))

print('== 1. per box (fresh heartbeats)')
print(f"{'host':34} {'prim':5} {'scrT':>5} {'free':>5} {'ifc':>3} {'big':>3} {'ifcDiskRes':>10} gate(mem/cpu/disk) slots  live pipelines  big sizes MB")
running_ids = set(); tot = collections.Counter()
for host in sorted(hb):
    docs = hb[host]
    prim = next((d.get('primary_pipe') for _, d in docs if d.get('primary_pipe')), None) or next((p for p, d in docs if d.get('primary')), '?')
    ifc = [d for p, d in docs if p == 'ifc']
    anyd = (ifc or [d for _, d in docs])[0]
    run = [r for d in ifc for r in d.get('running') or []]
    for _, d in docs:
        running_ids.update(r.get('id') for r in d.get('running') or [])
    big = [r for r in run if (r.get('size') or 0) >= BIG]
    g = (ifc[0].get('gate') if ifc else {}) or {}
    pl = collections.Counter()
    for p, d in docs:
        pl[p] += len(d.get('running') or [])
    tot['ifc'] += len(run); tot['big'] += len(big); tot['boxes'] += 1
    print(f"{host[:34]:34} {str(prim)[:5]:5} {anyd.get('disk_total_gb', 0) / 1024:5.1f} {anyd.get('disk_free_gb', 0) / 1024:5.1f} {len(run):3} {len(big):3} "
          f"{sum((r.get('disk') or 0) for r in run) / 2 ** 30:9.0f}G {str(g.get('ok_mem'))[0]}/{str(g.get('ok_cpu'))[0]}/{str(g.get('ok_disk'))[0]}"
          f"{'':12} {max([d.get('slots') or 0 for d in ifc] or [0]):3}  {dict(pl)}  {sorted(round((r.get('size') or 0) / 2 ** 20) for r in big)}")
print('totals', dict(tot))

print('== 2. open IFC queue (redo.json + jobs_reconvert.json) minus running, by input size')
redo = getj(f'{ST}/ifc/redo.json') or []
jr = getj(f'{ST}/ifc/jobs_reconvert.json') or []
jm = getj(f'{ST}/ifc/jobs.json') or []
jm = jm.get('jobs') if isinstance(jm, dict) else jm
size = {}
for j in (jm or []) + (jr or []):
    if isinstance(j, dict) and j.get('id'):
        size[j['id']] = j.get('size') or size.get(j['id'])
opn = set(redo) | {j['id'] for j in jr if isinstance(j, dict)}
wait = opn - running_ids
edges = [(0, 10), (10, 50), (50, 100), (100, 200), (200, 500), (500, 1 << 40)]


def mix(ids):
    c = collections.Counter()
    for i in ids:
        s = size.get(i)
        if s is None:
            c['unknown'] += 1; continue
        mb = s / 2 ** 20
        for lo, hi in edges:
            if lo <= mb < hi:
                c[f'{lo}-{hi if hi < 1 << 30 else "inf"} MB'] += 1; break
    return dict(sorted(c.items(), key=lambda kv: (kv[0] == 'unknown', int(kv[0].split('-')[0]) if kv[0] != 'unknown' else 0)))


print(f'open {len(opn)}, running now {len(opn & running_ids)}, waiting {len(wait)}')
print('waiting by size:', mix(wait))
print('running by size:', mix(opn & running_ids))
print(f'waiting >= 100 MB: {sum(1 for i in wait if (size.get(i) or 0) >= BIG)}')

print('== 3. finished IFC jobs >= 100 MB: STEP output (scratch proxy)')
idx = getb(f'{ST}/index.jsonl.gz')
sb = []
if idx:
    for l in gzip.decompress(idx).decode().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get('pipeline') == 'ifc' and (size.get(r.get('id')) or 0) >= BIG and r.get('step_bytes'):
            sb.append((r['step_bytes'], size[r['id']]))
if sb:
    v = sorted(x for x, _ in sb)
    print(f"n {len(v)}: STEP GB p50 {statistics.median(v) / 1e9:.1f}, p95 {v[int(len(v) * 0.95) - 1] / 1e9:.1f}, max {v[-1] / 1e9:.1f}; "
          f"ratio STEP/input p95 {sorted(x / s for x, s in sb)[int(len(sb) * 0.95) - 1]:.1f}")
else:
    print('no rows (index unreadable or no sizes)')

print('== 4. ap-southeast-1 boxes')
for host in sorted(h for h in hb if 'southeast' in h):
    docs = hb[host]
    s2 = [d for p, d in docs if p == 'sds2' and d.get('primary')]
    ifc = [d for p, d in docs if p == 'ifc']
    for d in s2:
        nrun = len(d.get('running') or []); oth = (d.get('others') or {}).get('running', 0); sl = d.get('slots') or 0
        g = d.get('gate') or {}
        print(f"{host}: SDS2 primary pid {d.get('pid')} running {nrun} (+{oth} other sds2 pids), slots {sl} -> assist-start threshold {max(1, sl // 2)}; "
              f"gate ok_cpu {g.get('ok_cpu')} ok_mem {g.get('ok_mem')}; IFC workers heartbeating: {len(ifc)} "
              f"({sum(len(x.get('running') or []) for x in ifc)} jobs); pipelines live: {sorted({p for p, _ in docs})}")
        lg = (getb(d['_key'].replace('/hosts/', '/logs/').replace('.json', '.log')) or b'').decode('utf-8', 'replace').splitlines()
        al = [x for x in lg if 'assist' in x.lower()]
        print('   last assist log lines:', al[-3:] if al else 'none in the log buffer')
    if not s2:
        print(f"{host}: no SDS2 primary heartbeat; pipelines live: {sorted({p for p, _ in docs})}")
PYEOF
