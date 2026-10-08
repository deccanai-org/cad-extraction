#!/bin/bash
# PARTIAL-TIER packaging service (owner 10-05: package every partial model, same projpkg4 format, separate folder packages/3d_partial/,
# counted separately, deduped: a project already in the perfect tier gets an ADD-ON with only its partial STEP). Runs on the coordinator.
# Each round: pkg_delta(write=True) in the partial namespace (state _state/packaging_partial, jobs _state/conv/package_partial/) for
# data-3 then data-4 -> package jobs in a process pool (one process per job, transient retries) -> results recorded; idle rounds sleep
# 10 min. First round: a 3-project canary (an add-on, an SDS2 job, an IFC/DB1 project) must pass package verify, else the service stops.
# Stop: touch /opt/pkgpartial/stop. Status: this script (idempotent).
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgpartial4; mkdir -p $D/logs $D/work; touch $D/canary_ok
if systemctl is-active -q z3pkgp-loop4; then echo "running since $(cat $D/started)"; tail -n 6 $D/loop.log | cut -c1-300; exit 0; fi
[ -f $D/canary_fail ] && { echo "CANARY FAILED"; cat $D/canary_fail; tail -n 20 $D/loop.log | cut -c1-300; exit 0; }
cat > $D/loop.py <<'PYEOF'
import os, sys, json, time, datetime, collections, traceback
sys.path.insert(0, '/opt/pkgpartial/kit')
from multiprocessing import Pool
import pkg, pkgcore as pc
assert pc.TIER == 'partial' and pc.ROUTE == '3d_partial' and 'packaging_partial' in pc.PSTATE
D = '/opt/pkgpartial4'; PROCS = int(os.environ.get('PKGP_PROCS', '20'))
TRANSIENT = ('SSLError', 'ConnectionError', 'ReadTimeout', 'EndpointConnectionError', 'IncompleteRead', 'ProtocolError', 'ResponseStreamingError')
def log(*a): print(datetime.datetime.utcnow().strftime('%H:%M:%S'), *a, flush=True)
def one(arg):
    i, job, ad = arg
    time.sleep(min(i, PROCS) * 4)
    r = None
    for attempt in range(6):
        try:
            r = pkg.package_job(job, workdir=f'{D}/work/{job["id"]}')
        except Exception as e:
            r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'packager_exception', 'error': f'{type(e).__name__}: {e}'[:300],
                 'trace': traceback.format_exc()[-1500:]}
            if any(t in r['trace'] for t in TRANSIENT) and attempt < 5:
                time.sleep(30 * (attempt + 1)); continue
        if r.get('status') == 'retry' and r.get('reason') == 'project_locked' and attempt < 5:
            time.sleep(120); continue
        break
    json.dump(r, open(f'{D}/logs/{job["id"]}.json', 'w'), indent=1, default=str)
    out = dict(r); out.pop('verify', None) if r.get('status') == 'ok' else None
    jk = pkg.JOBS_KEY if ad == 'zen3' else pkg.JOBS_KEY.replace('/jobs.json', f'/jobs_{ad}.json')
    out.update(id=job['id'], pipeline='package_partial', adapter=ad, finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))
    pc.s3c().put_object(Bucket=pc.BUCKET, Key=jk.rsplit('/', 1)[0] + f'/results/{job["id"]}.json', Body=json.dumps(out, default=str).encode(),
                        ContentType='application/json')
    ap = r.get('apply') or {}
    log(job['id'], ad, r.get('status'), r.get('reason') or r.get('note'), ap.get('status'), 'copied', ap.get('copied'), 'failed', len(ap.get('failed') or []),
        (r.get('verify') or {}).get('checks'), job['project_id'][:80])
    return job['id'], r.get('status'), ap.get('status'), ap.get('copied') or 0, (r.get('verify') or {}).get('ok')
def run(jobs, ad, procs):
    if not jobs: return []
    with Pool(min(procs, len(jobs)), maxtasksperchild=1) as pool:
        return list(pool.imap_unordered(one, [(i, j, ad) for i, j in enumerate(jobs)]))
def canary(jobs, ad):
    is_addon = lambda j: bool(pc.head(pc.BUCKET, f"{pc.DATASET}/3d/{j['project_id']}/project.json"))
    small = sorted(jobs, key=lambda j: j.get('size') or 0)
    pick = []
    for want in ('addon', 'sds2', 'other'):
        for j in small:
            if j in pick or (j.get('size') or 0) < 1e6: continue
            pl = {mk.split(':')[1] for mk in j.get('add') or []}
            if want == 'addon' and not is_addon(j): continue
            if want == 'sds2' and (pl != {'sds2'} or is_addon(j)): continue
            if want == 'other' and ('sds2' in pl or is_addon(j)): continue
            pick.append(j); break
    log('CANARY', ad, [(j['project_id'][:70], j.get('size')) for j in pick])
    res = run(pick, ad, 3)
    bad = [x for x in res if x[1] != 'ok' or x[4] is not True]
    if bad or len(res) < 3:
        open(f'{D}/canary_fail', 'w').write(json.dumps(res, default=str)); log('CANARY FAILED', res); sys.exit(3)
    open(f'{D}/canary_ok', 'w').write(json.dumps(res, default=str)); log('CANARY OK', res)
    return [j for j in jobs if j not in pick]
while not os.path.exists(f'{D}/stop'):
    busy = False
    for ad in ('zen4',):
        t0 = time.time()
        jobs, st = pkg.pkg_delta(ad, write=True)
        log('DELTA', ad, round(time.time() - t0), 's', json.dumps({k: st.get(k) for k in ('shipped_models', 'projects_with_shipped_step', 'projects_packaged',
            'placements', 'pending_jobs', 'pending_create', 'removals_pending', 'verify_failures', 'stuck_projects')}))
        if not jobs: continue
        busy = True
        if not os.path.exists(f'{D}/canary_ok'):
            jobs = canary(jobs, ad)
        res = run(sorted(jobs, key=lambda j: -(j.get('size') or 0)), ad, PROCS)
        log('ROUND', ad, 'jobs', len(res), dict(collections.Counter(x[1] for x in res)), 'copied', sum(x[3] for x in res))
        if os.path.exists(f'{D}/stop'): break
    if not busy:
        time.sleep(600)
log('stop flag: exiting')
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkgp-loop4 2>/dev/null
systemd-run --unit=z3pkgp-loop4 --collect --nice=5 --working-directory=/opt/pkgpartial/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_TIER=partial \
  --setenv=PKG_ALLOW_WRITE=1 --setenv=PKG_PARTIAL_REQUIRE_CODE='{"db1": "z3-db1-2026-10-01v"}' \
  --setenv=PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
  /bin/bash -c "/opt/conv/env/bin/python $D/loop.py >> $D/loop.log 2>&1; echo rc=\$? >> $D/loop.log"
sleep 30; echo "started: $(systemctl is-active z3pkgp-loop4)"; tail -n 3 $D/loop.log
