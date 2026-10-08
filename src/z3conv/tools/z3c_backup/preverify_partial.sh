#!/bin/bash
# full package verify of one tier now (incremental cache for the finisher): /opt/finish/verify_<tier>_cache.json = {pid: {checked_at, result}}
# usage: edit TIER below. Read-only on packages.
export AWS_DEFAULT_REGION=ap-south-1
TIER=partial; F=/opt/finish; mkdir -p $F
if systemctl is-active -q z3preverify-$TIER; then echo "running since $(cat $F/preverify_$TIER.started)"; tail -n 3 $F/preverify_$TIER.log; exit 0; fi
cat > $F/verify_cache.py <<'PYEOF'
import os, sys, json, time, collections, datetime
from multiprocessing import Pool
kit, cache_f = sys.argv[1], sys.argv[2]
sys.path.insert(0, kit); tier = os.environ.get('PKG_TIER', 'perfect')
import pkg, pkgcore as pc
keys = {}
for ad in ('zen3', 'zen4'):
    a = pkg.load_adapter(ad); rows = a.conv_rows(pc.get_bytes(pc.BUCKET, pkg.ad_index_key(a)))
    pm = (pc.get_json(pc.BUCKET, pkg.primary_key(a)) or {}).get('map') or {}
    sh, *_ = pkg.shipped_by_project(a, rows, None, primary=pm)
    keys.update({r['id']: r['step_key'] for r in sh.values()})
cache = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
pids = [p.rstrip('/').rsplit('/', 1)[-1] for p in pkg._prefixes(f'{pc.DATASET}/{pc.ROUTE}/')]
def lm(pid):     # last write to the project: its manifest
    h = pc.head(pc.BUCKET, f'{pc.DATASET}/{pc.ROUTE}/{pid}/manifest.jsonl')
    return h['LastModified'].timestamp() if h else 0
def one(pid):
    t0 = time.time(); m = lm(pid); c = cache.get(pid)
    if c and c.get('manifest_lm') == m and c['result'].get('ok'):
        return pid, c                                  # unchanged since a passing verify
    try: v = pc.verify_project(pc.BUCKET, pid, keys)
    except Exception as e: v = {'project_id': pid, 'ok': False, 'checks': {'verify_exception': 1}, 'error': str(e)[:200]}
    return pid, {'checked_at': t0, 'manifest_lm': m, 'result': v}
t0 = time.time()
with Pool(24) as pool:
    for i, (pid, c) in enumerate(pool.imap_unordered(one, pids, chunksize=1), 1):
        cache[pid] = c
        if i % 100 == 0:
            json.dump(cache, open(cache_f + '.tmp', 'w')); os.replace(cache_f + '.tmp', cache_f)
            print(datetime.datetime.utcnow().strftime('%H:%M:%S'), i, '/', len(pids), round(time.time() - t0), 's', flush=True)
for pid in list(cache):
    if pid not in pids: cache.pop(pid)                 # projects no longer present
json.dump(cache, open(cache_f + '.tmp', 'w')); os.replace(cache_f + '.tmp', cache_f)
agg = collections.Counter(); bad = 0
for c in cache.values():
    agg.update(c['result'].get('checks') or {}); bad += not c['result'].get('ok')
print('DONE', tier, len(cache), 'projects, failing', bad, dict(agg), round(time.time() - t0), 's', flush=True)
PYEOF
date -u +%FT%TZ > $F/preverify_$TIER.started
systemctl reset-failed z3preverify-$TIER 2>/dev/null
systemd-run --unit=z3preverify-$TIER --collect --nice=10 --working-directory=/opt/pkgpartial/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_TIER=partial '--setenv=PKG_PARTIAL_REQUIRE_CODE={"db1": "z3-db1-2026-10-01v"}' \
  --setenv=PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
  /bin/bash -c "/opt/conv/env/bin/python $F/verify_cache.py /opt/pkgpartial/kit $F/verify_${TIER}_cache.json > $F/preverify_$TIER.log 2>&1; echo rc=\$? >> $F/preverify_$TIER.log"
sleep 30; echo "started: $(systemctl is-active z3preverify-$TIER)"; tail -n 2 $F/preverify_$TIER.log
