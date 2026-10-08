#!/bin/bash
# Add the package files that resolve now (proven Disk-1/2 keys from the data-4 pkg-resolver + the 65 data-3 files recovered from their source
# archives) to their packages: the packager's OWN 'files' update jobs (pkg_delta, write=False, with PKG_D12MAP = the combined proven map),
# run like fleet package workers (one process per job, transient-error retries, staggered starts), results recorded under package/results/.
# Usage: ADAPTER=zen3|zen4 RUN=<name>. Kit /opt/pkgd4r2/kit (read_manifest fix). Idempotent: first call starts unit z3pkgfiles-$RUN.
export AWS_DEFAULT_REGION=ap-south-1; ADAPTER=zen4; RUN=zen4_r2
PY=/opt/conv/env/bin/python; ADAPTER=${ADAPTER:-zen4}; RUN=${RUN:-$ADAPTER}; D=/opt/pkgfiles/$RUN
MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz
mkdir -p $D/logs
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; cat $D/summary.txt; grep -v "^jobs" $D/driver.log | tail -n 40 | cut -c1-250; exit 0; fi
if systemctl is-active -q z3pkgfiles-$RUN; then echo "running since $(cat $D/started)"; grep -c " ok \| fail " $D/driver.log; tail -n 4 $D/driver.log | cut -c1-250; exit 0; fi
cat > $D/driver.py <<'PYEOF'
import os, sys, json, datetime, collections, traceback, time
from multiprocessing import Pool
D = os.environ['PKGF_D']; ADAPTER = os.environ['PKGF_ADAPTER']
sys.path.insert(0, '/opt/pkgd4r2/kit')
import pkg, pkgcore as pc
RP = 'cad-disk-extract/zenitude-data-3/_state/conv/package/results/'
TRANSIENT = ('SSLError', 'ConnectionError', 'ReadTimeout', 'EndpointConnectionError', 'IncompleteRead', 'ProtocolError', 'ResponseStreamingError')
def one(arg):
    i, job = arg
    time.sleep(min(i, 12) * 8)                                    # staggered starts: 12 processes do not load the index at once
    s3 = pc.s3c(); r = None
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
    out.update(id=job['id'], pipeline='package', adapter=ADAPTER, finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
               recorded_by='pkg_files_run (lead): files job with the combined proven disk12 map')
    s3.put_object(Bucket=pc.BUCKET, Key=f'{RP}{job["id"]}.json', Body=json.dumps(out, default=str).encode(), ContentType='application/json')
    ap = r.get('apply') or {}
    print(job['id'], r.get('status'), r.get('reason'), ap.get('status'), 'copied', ap.get('copied'), 'failed', len(ap.get('failed') or []),
          (r.get('verify') or {}).get('checks'), job['project_id'][:90], flush=True)
    return r.get('status'), ap.get('status'), ap.get('copied') or 0
if __name__ == '__main__':
    import hashlib
    ad0 = pkg.load_adapter(ADAPTER)
    idx = pc.get_bytes(pc.BUCKET, pkg.ad_index_key(ad0))          # one index read: the delta and its snapshot use the same bytes
    jobs, st = pkg.pkg_delta(ADAPTER, index_bytes=idx, write=False)
    snap = f"{pc.PSTATE}/index_snapshots/{hashlib.sha256(idx).hexdigest()[:16]}.jsonl.gz"
    if not pc.head(pc.BUCKET, snap):                              # what the coordinator's delta writes (content-addressed copy)
        pc.s3c().put_object(Bucket=pc.BUCKET, Key=snap, Body=idx, ContentType='application/gzip'); print('wrote snapshot', snap, flush=True)
    # data-4 (zen4): no fleet worker runs its jobs -> run every job (new class-1 adds + files); data-3: fleet workers run adds -> files only
    fj = jobs if ADAPTER == 'zen4' else [j for j in jobs if j.get('files')]
    print('jobs', len(jobs), 'selected', len(fj), 'files jobs', sum(1 for j in jobs if j.get('files')), 'status',
          json.dumps({k: st.get(k) for k in ('pending_jobs', 'shipped_models', 'placements')}), flush=True)
    miss = [j for j in fj if not pc.head(pc.BUCKET, j['index_key'])]
    if miss:
        print('index snapshot missing for', len(miss), 'jobs: stop', flush=True); sys.exit(2)
    json.dump(fj, open(f'{D}/files_jobs.json', 'w'), indent=1)
    with Pool(12, maxtasksperchild=1) as pool:
        res = list(pool.imap_unordered(one, list(enumerate(sorted(fj, key=lambda j: -(j.get('size') or 0))))))
    open(f'{D}/summary.txt', 'w').write(f"files jobs {len(fj)} status {dict(collections.Counter(s for s, _, _ in res))} "
                                        f"apply {dict(collections.Counter(a for _, a, _ in res))} files copied {sum(c for _, _, c in res)}\n")
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkgfiles-$RUN 2>/dev/null
systemd-run --unit=z3pkgfiles-$RUN --collect --nice=5 --working-directory=/opt/pkgd4r2/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 \
  --setenv=PKG_ALLOW_WRITE=1 --setenv=PKG_D12MAP=$MAP --setenv=PKGF_D=$D --setenv=PKGF_ADAPTER=$ADAPTER /bin/bash -c \
  "$PY $D/driver.py > $D/driver.log 2>&1; echo rc=\$? >> $D/driver.log; date -u +%FT%TZ > $D/finished"
sleep 60; echo "started: $(systemctl is-active z3pkgfiles-$RUN)"; tail -n 3 $D/driver.log | cut -c1-300
