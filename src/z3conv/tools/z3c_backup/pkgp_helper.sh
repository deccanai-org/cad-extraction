#!/bin/bash
# Partial-tier packaging HELPER on a conversion box (owner 10-06: use the fleet's spare capacity for the partial packaging).
# Takes small data-3 partial jobs (archive <= 3 GB) from the coordinator's job list, 4 at a time, only while the box has >= 60 GB free;
# skips jobs already done or locked; records results like the coordinator. On box power-off (SIGTERM) each job releases its lock.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgphelper; mkdir -p $D/kit $D/work
if systemctl is-active -q z3pkgp-helper; then echo "helper running since $(cat $D/started): ok $(grep -c ' ok ' $D/helper.log) fail $(grep -c ' fail ' $D/helper.log)"; exit 0; fi
avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
[ "$avail" -lt 120 ] && { echo "skip: only ${avail} GB free"; exit 0; }
for f in pkgcore.py pkg.py adapter_zen3.py adapter_zen4.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $D/kit/$f || { echo "kit download failed"; exit 1; }; done
cat > $D/helper.py <<'PYEOF'
import os, sys, json, time, signal, socket, random, datetime, traceback
sys.path.insert(0, '/opt/pkgphelper/kit')
from multiprocessing import Pool
import pkg, pkgcore as pc
assert pc.TIER == 'partial' and pc.ROUTE == '3d_partial'
D = '/opt/pkgphelper'; MAXSZ = 3e9; PROCS = 4; HOST = socket.gethostname()
JK = pkg.JOBS_KEY; RP = JK.rsplit('/', 1)[0] + '/results/'
TRANSIENT = ('SSLError', 'ConnectionError', 'ReadTimeout', 'EndpointConnectionError', 'IncompleteRead', 'ProtocolError', 'ResponseStreamingError')
def log(*a): print(datetime.datetime.utcnow().strftime('%H:%M:%S'), *a, flush=True)
def mem_gb():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1]) / 1048576
def term(*a): raise SystemExit(0)
def one(job):
    signal.signal(signal.SIGTERM, term)
    if pc.head(pc.BUCKET, f"{RP}{job['id']}.json"): return job['id'], 'already_done', 0
    if pc.head(pc.BUCKET, f"{pc.PSTATE}/locks/{job['project_id']}.json"): return job['id'], 'locked_elsewhere', 0
    while mem_gb() < 60: time.sleep(30)
    r = None
    for attempt in range(4):
        try:
            r = pkg.package_job(job, workdir=f"{D}/work/{job['id']}")
        except Exception as e:
            tb = traceback.format_exc()[-1200:]
            r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'packager_exception', 'error': f'{type(e).__name__}: {e}'[:300], 'trace': tb}
            if any(t in tb for t in TRANSIENT) and attempt < 3: time.sleep(30 * (attempt + 1)); continue
        break
    if r.get('status') == 'retry': return job['id'], 'locked_elsewhere', 0
    out = dict(r); out.pop('verify', None) if r.get('status') == 'ok' else None
    out.update(id=job['id'], pipeline='package_partial', adapter='zen3', finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), recorded_by=f'helper:{HOST}')
    pc.s3c().put_object(Bucket=pc.BUCKET, Key=f"{RP}{job['id']}.json", Body=json.dumps(out, default=str).encode(), ContentType='application/json')
    ap = r.get('apply') or {}
    log(job['id'], r.get('status'), r.get('reason') or r.get('note'), 'copied', ap.get('copied'), (r.get('verify') or {}).get('checks'), job['project_id'][:70])
    return job['id'], r.get('status'), ap.get('copied') or 0
idle = 0
while not os.path.exists(f'{D}/stop'):
    jobs = (pc.get_json(pc.BUCKET, JK) or {}).get('jobs') or []
    todo = [j for j in jobs if (j.get('size') or 0) <= MAXSZ]
    random.Random(HOST).shuffle(todo)
    log('job list', len(jobs), 'small', len(todo))
    done_any = False
    with Pool(PROCS, maxtasksperchild=1) as pool:
        for jid, st, n in pool.imap_unordered(one, todo):
            if st in ('ok', 'fail'): done_any = True
    idle = 0 if done_any else idle + 1
    if idle >= 3: log('nothing left for the helper: exiting'); break
    time.sleep(300)
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3pkgp-helper 2>/dev/null
systemd-run --unit=z3pkgp-helper --collect --nice=10 --working-directory=$D/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_TIER=partial \
  --setenv=PKG_ALLOW_WRITE=1 --setenv='PKG_PARTIAL_REQUIRE_CODE={"db1": "z3-db1-2026-10-01v"}' \
  --setenv=PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
  /bin/bash -c "/opt/conv/env/bin/python $D/helper.py >> $D/helper.log 2>&1; echo rc=\$? >> $D/helper.log"
sleep 25; echo "helper: $(systemctl is-active z3pkgp-helper) mem ${avail}G"; tail -n 2 $D/helper.log | cut -c1-200
