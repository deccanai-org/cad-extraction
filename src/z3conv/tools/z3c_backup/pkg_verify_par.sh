#!/bin/bash
# READ-ONLY parallel verify of every package (12 processes, one result file per project -> resumable). data-3 projects against zen3
# shipped keys, data-4 against zen4. Kit: /opt/pkgd4r2/kit (read_manifest split on '\n'). No S3 writes. SKIP=file of project ids to skip.
# Usage: RUN=<name> [ONLY=<file of ids>] [SKIP=<file>]. Idempotent: first call starts unit z3pkg-vpar-$RUN; later calls print progress.
export AWS_DEFAULT_REGION=ap-south-1; RUN=a; SKIP_FROM_JOBS=/opt/pkgd4r2/jobs_zen4.json
PY=/opt/conv/env/bin/python; RUN=${RUN:-a}; O=/opt/pkgverify3/$RUN; K=/opt/pkgd4r2/kit
mkdir -p $O/res
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; cat $O/summary.txt | cut -c1-600; exit 0; fi
if systemctl is-active -q z3pkg-vpar-$RUN; then echo "running since $(cat $O/started): $(ls $O/res | wc -l) done of $(cat $O/n 2>/dev/null)"; tail -n 2 $O/log.txt; exit 0; fi
cat > $O/run.py <<'PYEOF'
import os, sys, json, hashlib, collections, time
from multiprocessing import Pool
sys.path.insert(0, '/opt/pkgd4r2/kit'); os.environ['PKG_ALLOW_WRITE'] = '0'
import pkgcore as pc, pkg
O = sys.argv[1]; ONLY = os.environ.get('ONLY'); SKIP = os.environ.get('SKIP')
def keyfile(p): return f'{O}/res/{hashlib.sha1(p.encode()).hexdigest()}.json'
KEYS = {}
def init():
    for adn in ('zen3', 'zen4'):
        ad = pkg.load_adapter(adn)
        KEYS[adn] = {r['id']: r['step_key'] for r in pkg.shipped_by_project(ad, ad.conv_rows())[0].values()}
def one(p):
    if os.path.exists(keyfile(p)): return
    adn = 'zen4' if p.startswith('Zentitude-data-4__') else 'zen3'
    try: v = pc.verify_project(pc.BUCKET, p, KEYS[adn])
    except Exception as e: v = {'project_id': p, 'ok': False, 'checks': {'verify_exception': 1}, 'examples': {'verify_exception': [f'{type(e).__name__}: {e}'[:300]]}}
    v['adapter'] = adn; v['verified_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    json.dump(v, open(keyfile(p) + '.tmp', 'w')); os.replace(keyfile(p) + '.tmp', keyfile(p))
if __name__ == '__main__':
    pids = [p.rstrip('/').rsplit('/', 1)[-1] for p in pkg._prefixes(f'{pc.DATASET}/{pc.ROUTE}/')]
    if ONLY: pids = [p for p in pids if p in set(open(ONLY).read().splitlines())]
    if SKIP: pids = [p for p in pids if p not in set(open(SKIP).read().splitlines())]
    open(f'{O}/n', 'w').write(str(len(pids))); print('projects', len(pids), flush=True)
    with Pool(12, initializer=init) as pool:
        for i, _ in enumerate(pool.imap_unordered(one, pids), 1):
            if i % 25 == 0: print(i, flush=True)
    res = [json.load(open(keyfile(p))) for p in pids]
    lines = []
    for adn in ('zen3', 'zen4'):
        rs = [v for v in res if v['adapter'] == adn]; agg = collections.Counter(); inf = collections.Counter()
        for v in rs: agg.update(v.get('checks') or {}); inf.update(v.get('info') or {})
        lines.append(f"{adn}: projects {len(rs)} ok {sum(1 for v in rs if v['ok'])} rows {sum(v.get('rows') or 0 for v in rs)} objects {sum(v.get('objects') or 0 for v in rs)} checks {dict(agg)} info {dict(inf)}")
        for v in rs:
            if not v['ok']: lines.append(f"  FAIL {v['project_id'][:120]} {v.get('checks')} {json.dumps(v.get('examples'))[:400]}")
    open(f'{O}/summary.txt', 'w').write('\n'.join(lines) + '\n'); print('\n'.join(lines))
PYEOF
if [ -n "$SKIP_FROM_JOBS" ]; then $PY -c "import json;d=json.load(open('$SKIP_FROM_JOBS'));j=d['jobs'] if isinstance(d,dict) else d;print('\n'.join(x['project_id'] for x in j))" > $O/skip.txt; SKIP=$O/skip.txt; fi
date -u +%FT%TZ > $O/started
systemctl reset-failed z3pkg-vpar-$RUN 2>/dev/null
systemd-run --unit=z3pkg-vpar-$RUN --collect --working-directory=$K --setenv=AWS_DEFAULT_REGION=ap-south-1 ${ONLY:+--setenv=ONLY=$ONLY} ${SKIP:+--setenv=SKIP=$SKIP} \
  /bin/bash -c "$PY $O/run.py $O > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 30; echo "started: $(systemctl is-active z3pkg-vpar-$RUN)"; tail -n 3 $O/log.txt
