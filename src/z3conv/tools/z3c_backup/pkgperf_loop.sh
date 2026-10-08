#!/bin/bash
# PERFECT-TIER packaging service (unchanged packager kit /opt/pkgd4r2/kit): every round, for data-3 and data-4, the packager's own delta
# (write=False: the coordinator hook owns the perfect-tier jobs list) + the index snapshot the jobs read, then every open job in a process
# pool; idle rounds sleep 15 min. New class-1 models (e.g. DB1 code v) are packaged within a round. Stop: touch /opt/pkgperf/stop.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgperf; mkdir -p $D/logs $D/work
if systemctl is-active -q z3pkgperf-loop; then echo "running since $(cat $D/started)"; tail -n 6 $D/loop.log | cut -c1-300; exit 0; fi
cat > $D/loop.py <<'PYEOF'
import os, sys, json, time, datetime, collections, traceback, hashlib
sys.path.insert(0, '/opt/pkgd4r2/kit')
from multiprocessing import Pool
import pkg, pkgcore as pc
assert getattr(pc, 'ROUTE', '3d') == '3d' and pc.PSTATE == 'cad-disk-extract/_state/packaging'
D = '/opt/pkgperf'; RP = 'cad-disk-extract/zenitude-data-3/_state/conv/package/results/'
TRANSIENT = ('SSLError', 'ConnectionError', 'ReadTimeout', 'EndpointConnectionError', 'IncompleteRead', 'ProtocolError', 'ResponseStreamingError')
def log(*a): print(datetime.datetime.utcnow().strftime('%H:%M:%S'), *a, flush=True)
def one(arg):
    i, job, ad = arg
    time.sleep(min(i, 8) * 4); r = None
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
    out.update(id=job['id'], pipeline='package', adapter=ad, finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), recorded_by='pkgperf_loop')
    pc.s3c().put_object(Bucket=pc.BUCKET, Key=f'{RP}{job["id"]}.json', Body=json.dumps(out, default=str).encode(), ContentType='application/json')
    ap = r.get('apply') or {}
    log(job['id'], ad, r.get('status'), r.get('reason') or r.get('note'), ap.get('status'), 'copied', ap.get('copied'), (r.get('verify') or {}).get('checks'), job['project_id'][:80])
    return r.get('status')
while not os.path.exists(f'{D}/stop'):
    busy = False
    for ad in ('zen3', 'zen4'):
        a0 = pkg.load_adapter(ad); idx = pc.get_bytes(pc.BUCKET, pkg.ad_index_key(a0))
        jobs, st = pkg.pkg_delta(ad, index_bytes=idx, write=False)
        snap = f"{pc.PSTATE}/index_snapshots/{hashlib.sha256(idx).hexdigest()[:16]}.jsonl.gz"
        if jobs and not pc.head(pc.BUCKET, snap):
            pc.s3c().put_object(Bucket=pc.BUCKET, Key=snap, Body=idx, ContentType='application/gzip')
        log('DELTA', ad, json.dumps({k: st.get(k) for k in ('shipped_models', 'projects_packaged', 'placements', 'pending_jobs', 'pending_create', 'removals_pending', 'verify_failures', 'stuck_projects')}))
        if not jobs: continue
        busy = True
        with Pool(min(8, len(jobs)), maxtasksperchild=1) as pool:
            res = list(pool.imap_unordered(one, [(i, j, ad) for i, j in enumerate(sorted(jobs, key=lambda j: -(j.get('size') or 0)))]))
        log('ROUND', ad, dict(collections.Counter(res)))
    if not busy: time.sleep(900)
log('stop flag: exiting')
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkgperf-loop 2>/dev/null
systemd-run --unit=z3pkgperf-loop --collect --nice=5 --working-directory=/opt/pkgd4r2/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_ALLOW_WRITE=1 \
  --setenv=PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
  /bin/bash -c "/opt/conv/env/bin/python $D/loop.py >> $D/loop.log 2>&1; echo rc=\$? >> $D/loop.log"
sleep 30; echo "started: $(systemctl is-active z3pkgperf-loop)"; tail -n 3 $D/loop.log
