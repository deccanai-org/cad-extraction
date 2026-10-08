#!/bin/bash
# FINISHER (owner 10-06: "fully finish by morning, perfect numbers"): runs on the coordinator with its instance role (no operator login).
# Every 10 min: done = (no conversion re-run open on either disk) AND (both partial-tier deltas after that report 0 jobs) AND (perfect
# tier has nothing to place). Then once: full package verify of every project in both tiers, final stats (perfect f1, partial p1), class
# tables by disk / origin, owner-removal lists; everything is pushed to cad-disk-extract/_state/report/out/ with FINISH_DONE.json.
# Never deletes anything. Status: this script (idempotent). Stop: touch /opt/finish/stop.
export AWS_DEFAULT_REGION=ap-south-1
F=/opt/finish; mkdir -p $F
if systemctl is-active -q z3finish; then echo "running since $(cat $F/started)"; tail -n 5 $F/finish.log | cut -c1-300; exit 0; fi
[ -f $F/FINISH_DONE.json ] && { echo "FINISHED"; cat $F/FINISH_DONE.json | head -c 3000; exit 0; }
cp /tmp/finisher_stats_f1.sh $F/rep_stats_f1.sh 2>/dev/null; cp /tmp/finisher_stats_p1.sh $F/rep_stats_p1.sh 2>/dev/null
cat > $F/finish.py <<'PYEOF'
import os, sys, json, gzip, io, time, datetime, subprocess, collections, re
import boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; F = '/opt/finish'
OUT = 'cad-disk-extract/_state/report/out/'
IDX = {'data-3': 'cad-disk-extract/zenitude-data-3/_state/conv', 'data-4': 'cad-disk-extract/zentitude-data-4/_state/conv2'}
DB1V = 'z3-db1-2026-10-01v'
def log(*a): print(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), *a, flush=True)
def getj(k):
    try:
        b = s3.get_object(Bucket=B, Key=k)['Body'].read()
        return json.loads(gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b)
    except Exception: return None
def index_rows(disk):
    b = s3.get_object(Bucket=B, Key=f'{IDX[disk]}/index.jsonl.gz')['Body'].read()
    return [json.loads(l) for l in gzip.decompress(b).decode().split('\n') if l.strip()]
STILL = {}
def conv_open():
    """open conversion work: DB1 rows (class 1/2/3) not yet on code v, plus every redo / jobs_reconvert entry of every pipeline"""
    out = {}
    for disk in IDX:
        rows = index_rows(disk)
        # a row never converted (no converter code: missing or 0-byte input) can never move to code v and does not count as open
        # (10-06 06:35 PDT) one 30.7 MB DB1 model (Littleton Elementary) is starved on the smallest box (812 CPU-s in 5 h, disk-wait); it keeps
        # running and is packaged automatically if it completes, but the final pass does not wait for it: listed as still converting
        IGN = ('2a7c0357cd2cf339',)
        still = [r['id'] for r in rows if r['pipeline'] == 'db1' and r.get('class') in (1, 2, 3) and r.get('converter_code')
                 and r.get('converter_code') != DB1V and r['id'].startswith(IGN)]
        if still: out[f'{disk}|db1_still_converting_not_waited'] = 0; STILL[disk] = still
        out[f'{disk}|db1_not_on_v'] = sum(1 for r in rows if r['pipeline'] == 'db1' and r.get('class') in (1, 2, 3) and r.get('converter_code')
                                          and r.get('converter_code') != DB1V and not r['id'].startswith(IGN))
        for p in ('ifc', 'db1', 'sds2'):
            for k in ('redo.json', 'jobs_reconvert.json'):
                if p == 'db1' and k == 'redo.json':
                    continue          # DB1 is judged by db1_not_on_v (the redo list also holds 10 models whose input was never found)
                d = getj(f'{IDX[disk]}/{p}/{k}') or []
                d = d.get('ids', d.get('jobs', d.get('entries', []))) if isinstance(d, dict) else d
                if k == 'jobs_reconvert.json':   # entries without an input_key can never run (no input on this disk / empty file)
                    d = [x for x in d if isinstance(x, dict) and x.get('input_key')]
                out[f'{disk}|{p}|{k}'] = len(d)
    return out
def last_delta(logf, ad):
    if not os.path.exists(logf): return None, None
    t = None; st = None
    for l in open(logf, errors='replace'):
        m = re.match(r'(\d\d:\d\d:\d\d) DELTA ' + ad + r' (?:\d+ s )?(\{.*\})', l.strip())
        if m: t = m.group(1); st = json.loads(m.group(2))
    return t, st
def tod(t):     # HH:MM:SS today (UTC) -> epoch; logs roll over midnight UTC rarely matters for ordering within a day
    now = datetime.datetime.utcnow(); h, m, s = map(int, t.split(':'))
    dt = now.replace(hour=h, minute=m, second=s, microsecond=0)
    if dt > now + datetime.timedelta(minutes=5): dt -= datetime.timedelta(days=1)
    return dt.timestamp()
conv_done_at = None
while not os.path.exists(f'{F}/stop'):
    try:
        co = conv_open(); open_n = sum(co.values())
        if open_n == 0 and conv_done_at is None:
            conv_done_at = time.time(); log('CONVERSION DONE', json.dumps(co))
        elif open_n:
            conv_done_at = None; log('conversion open', open_n, json.dumps({k: v for k, v in co.items() if v}))
        ready = conv_done_at is not None
        dl = {}
        for name, logf, ad in (('partial-3', '/opt/pkgpartial/loop.log', 'zen3'), ('partial-4', '/opt/pkgpartial4/loop.log', 'zen4'),
                               ('perfect-3', '/opt/pkgperf/loop.log', 'zen3'), ('perfect-4', '/opt/pkgperf/loop.log', 'zen4')):
            t, st = last_delta(logf, ad); dl[name] = (t, (st or {}).get('pending_jobs'), (st or {}).get('verify_failures'), (st or {}).get('stuck_projects'))
            fresh = t is not None and conv_done_at is not None and tod(t) > conv_done_at + 60
            limit = 1 if name == 'perfect-3' else 0          # perfect data-3 keeps one no-op refresh job (ok, copies 0) every round
            ready = ready and fresh and st is not None and (st.get('pending_jobs') or 0) <= limit
        log('packaging', json.dumps(dl), 'READY' if ready else '')
        if ready: break
    except Exception as e:
        log('check error', type(e).__name__, str(e)[:300])
    time.sleep(600)
if os.path.exists(f'{F}/stop'): log('stop flag'); sys.exit(0)
log('ALL DONE: final verify + stats')
summary = {'done_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'conversion_open': co, 'last_deltas': dl,
           'still_converting_not_waited': STILL}
# ---- partial tier: objects left by an earlier failed attempt that no manifest row lists are queued for the owner (never deleted), exactly
# as the packager's own update pass does (reason orphan_unlisted); only for packages that have a manifest
PST = 'cad-disk-extract/_state/packaging_partial'; PP = 'cad-disk-extract/dataset/packages/3d_partial/'
try:
    vc = json.load(open(f'{F}/verify_partial_cache.json')) if os.path.exists(f'{F}/verify_partial_cache.json') else {}
    cand = [p for p, c in vc.items() if (c['result'].get('checks') or {}).get('orphan_object')]
    nq = 0
    for pid in cand:
        try: man = s3.get_object(Bucket=B, Key=f'{PP}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
        except Exception: continue
        listed = {json.loads(l)['relpath'] for l in man.split('\n') if l.strip()} | {'project.json', 'manifest.jsonl'}
        keys = [o['Key'][len(f'{PP}{pid}/'):] for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{PP}{pid}/') for o in pg.get('Contents') or []]
        orph = sorted(set(keys) - listed)
        if not orph: continue
        prev = getj(f'{PST}/removal_objects/{pid}.json') or {}
        have = {o['relpath'] for o in prev.get('objects') or []}
        new = [{'relpath': k, 'reason': 'orphan_unlisted', 'queued_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'queued_by': 'finisher'} for k in orph if k not in have]
        if new:
            s3.put_object(Bucket=B, Key=f'{PST}/removal_objects/{pid}.json', ContentType='application/json',
                          Body=json.dumps({'project_id': pid, 'updated': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'objects': list(prev.get('objects') or []) + new}, indent=1).encode())
            nq += len(new)
    log('orphans queued for owner review (partial tier)', nq, 'in', len(cand), 'packages'); summary['partial_orphans_queued'] = nq
except Exception as e:
    log('orphan queue error', str(e)[:300])
# ---- full package verify, both tiers, incremental: verify_cache.py (installed by preverify.sh) re-checks every project whose manifest
# changed since its last passing verify, and everything never verified; the summary is built from the whole cache
envb = dict(os.environ, AWS_DEFAULT_REGION='ap-south-1', PKG_D12MAP='s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz')
while subprocess.run(['systemctl', 'is-active', '-q', 'z3preverify-perfect']).returncode == 0 or subprocess.run(['systemctl', 'is-active', '-q', 'z3preverify-partial']).returncode == 0:
    log('waiting for a running pre-verify'); time.sleep(120)
for tier, kit, envx in (('perfect', '/opt/pkgd4r2/kit', {}), ('partial', '/opt/pkgpartial/kit', {'PKG_TIER': 'partial', 'PKG_PARTIAL_REQUIRE_CODE': json.dumps({'db1': DB1V})})):
    t0 = time.time(); e = dict(envb); e.pop('PKG_TIER', None); e.update(envx)
    r = subprocess.run(['/opt/conv/env/bin/python', f'{F}/verify_cache.py', kit, f'{F}/verify_{tier}_cache.json'], env=e, cwd=kit, capture_output=True, text=True)
    log('verify', tier, 'rc', r.returncode, round(time.time() - t0), 's', r.stdout.strip()[-300:], r.stderr.strip()[-600:] if r.returncode else '')
    cache = json.load(open(f'{F}/verify_{tier}_cache.json')) if os.path.exists(f'{F}/verify_{tier}_cache.json') else {}
    agg = collections.Counter(); failed = []; only_rm = 0
    for pid, c in cache.items():
        v = c['result']; agg.update(v.get('checks') or {})
        if not v.get('ok'):
            failed.append({'project_id': pid, 'checks': v.get('checks'), 'examples': v.get('examples')})
            if set(v.get('checks') or {}) <= {'step_not_shipped'}: only_rm += 1
    out = {'tier': tier, 'projects': len(cache), 'ok': len(cache) - len(failed), 'checks': dict(agg),
           'only_step_not_shipped (awaiting owner-approved removal)': only_rm, 'failed': failed[:300]}
    json.dump(out, open(f'{F}/verify_{tier}.json', 'w'), indent=1, default=str)
    summary[f'verify_{tier}'] = {k: out[k] for k in ('projects', 'ok', 'checks', 'only_step_not_shipped (awaiting owner-approved removal)')}
# ---- final stats (perfect f1, partial p1): the report's rep_stats units, waited for
for run, sh in (('f1', f'{F}/rep_stats_f1.sh'), ('p1', f'{F}/rep_stats_p1.sh')):
    subprocess.run(['bash', sh], capture_output=True, text=True)
    while subprocess.run(['systemctl', 'is-active', '-q', f'z3repstats-{run}']).returncode == 0: time.sleep(30)
    st = json.load(open(f'/opt/report/out/stats_{run}.json')) if os.path.exists(f'/opt/report/out/stats_{run}.json') else {}
    log('stats', run, st.get('projects'), (st.get('distinct') or {}).get('total_files')); summary[f'stats_{run}'] = {'projects': st.get('projects'), 'at': st.get('at')}
# ---- class tables by disk and exact origin
D1 = set(json.load(open('/opt/report/z4_disk12_duplicates.json'))); D2 = set(json.load(open('/opt/report/disk2_in_z3.json'))['z3_in_d2'])
def arch(p):
    a = p.split(' :: ')[0]; return a.split('/', 1)[1] if '/' in a else a
def tab(rows):
    c = collections.Counter((r['pipeline'], r.get('class')) for r in rows); tot = collections.Counter(r.get('class') for r in rows)
    return {'n': len(rows), 'by_class': {str(k): v for k, v in tot.items()}, 'by_type': {p: {str(k): c[(p, k)] for k in (1, 2, 3, None) if c[(p, k)]} for p in ('ifc', 'db1', 'sds2')}}
r3 = index_rows('data-3'); r4 = index_rows('data-4')
cls = {'data-3': tab(r3), 'data-4': tab(r4),
       'disk-2': tab([r for r in r3 if any(arch(p) in D2 for p in r.get('paths') or [])]), 'data-3-only': tab([r for r in r3 if not any(arch(p) in D2 for p in r.get('paths') or [])]),
       'disk-1': tab([r for r in r4 if any(arch(p) in D1 for p in r.get('paths') or [])]), 'data-4-only': tab([r for r in r4 if not any(arch(p) in D1 for p in r.get('paths') or [])])}
json.dump(cls, open('/opt/report/out/class_final.json', 'w'), indent=1); summary['class'] = {k: v['by_class'] for k, v in cls.items()}
# ---- owner-approval lists (never applied here)
for tier, st in (('perfect', 'cad-disk-extract/_state/packaging'), ('partial', 'cad-disk-extract/_state/packaging_partial')):
    b = b''
    try: b = s3.get_object(Bucket=B, Key=f'{st}/removals_pending.jsonl')['Body'].read()
    except Exception: pass
    rows = [json.loads(l) for l in b.decode().split('\n') if l.strip()]
    summary[f'removals_pending_{tier}'] = dict(collections.Counter(r.get('reason', '').split(':')[0] for r in rows))
for k in ('verify_perfect.json', 'verify_partial.json'):
    if os.path.exists(f'{F}/{k}'): subprocess.run(['cp', f'{F}/{k}', f'/opt/report/out/{k}'])
json.dump(summary, open(f'{F}/FINISH_DONE.json', 'w'), indent=1, default=str)
subprocess.run(['cp', f'{F}/FINISH_DONE.json', '/opt/report/out/FINISH_DONE.json'])
subprocess.run(['aws', 's3', 'sync', '--only-show-errors', '/opt/report/out/', f's3://{B}/{OUT}', '--exclude', '*.log', '--exclude', '*.started', '--region', 'ap-south-1'])
log('FINISHED: results in', OUT)
PYEOF
date -u +%FT%TZ > $F/started
systemctl reset-failed z3finish 2>/dev/null
systemd-run --unit=z3finish --collect --nice=8 --working-directory=$F --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c "/opt/report/venv/bin/python $F/finish.py >> $F/finish.log 2>&1; echo rc=\$? >> $F/finish.log"
sleep 40; echo "started: $(systemctl is-active z3finish)"; tail -n 4 $F/finish.log | cut -c1-400
