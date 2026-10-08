#!/bin/bash
# READ-ONLY verify of every package under bim dataset/packages/3d/: data-3 projects against the zen3 adapter's shipped keys,
# data-4 projects against zen4's. No PKG_ALLOW_WRITE; no S3 writes at all (results stay on the box in $O).
# Idempotent: first call starts transient unit z3pkg-verify2; later calls print progress / the summary.
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/pkgverify2_${RUN:-r1}; K=/opt/pkgd4/kit
mkdir -p $O
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; cat $O/summary.txt; exit 0; fi
if systemctl is-active -q z3pkg-verify2; then echo "running since $(cat $O/started)"; tail -n 3 $O/log.txt; exit 0; fi
grep -m1 -o "pkg-2026-10-02[a-z]" $K/pkgcore.py
cat > $O/run.py <<'PYEOF'
import os, sys, json, collections, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, '/opt/pkgd4/kit')
os.environ['PKG_ALLOW_WRITE'] = '0'
import pkgcore as pc, pkg
O = sys.argv[1]
keys = {}
for adn in ('zen3', 'zen4'):
    ad = pkg.load_adapter(adn)
    shipped = pkg.shipped_by_project(ad, ad.conv_rows())[0]
    keys[adn] = {r['id']: r['step_key'] for r in shipped.values()}
    print(adn, 'shipped', len(keys[adn]), flush=True)
pids = [p.rstrip('/').rsplit('/', 1)[-1] for p in pkg._prefixes(f'{pc.DATASET}/{pc.ROUTE}/')]
print('projects', len(pids), flush=True)
def one(p):
    adn = 'zen4' if p.startswith('Zentitude-data-4__') else 'zen3'
    try:
        v = pc.verify_project(pc.BUCKET, p, keys[adn])
    except Exception as e:
        v = {'project_id': p, 'ok': False, 'checks': {'verify_exception': 1}, 'examples': {'verify_exception': [f'{type(e).__name__}: {e}'[:300]]}}
    v['adapter'] = adn
    return v
res = []; t0 = time.time()
with ThreadPoolExecutor(12) as tp:
    fs = [tp.submit(one, p) for p in pids]
    for i, f in enumerate(as_completed(fs), 1):
        res.append(f.result())
        if i % 25 == 0: print(f'{i}/{len(pids)} {time.time()-t0:.0f}s', flush=True)
json.dump(res, open(f'{O}/results.json', 'w'))
lines = []
for adn in ('zen3', 'zen4'):
    rs = [v for v in res if v['adapter'] == adn]; agg = collections.Counter(); inf = collections.Counter()
    for v in rs: agg.update(v.get('checks') or {}); inf.update(v.get('info') or {})
    lines.append(f"{adn}: projects {len(rs)} ok {sum(1 for v in rs if v['ok'])} rows {sum(v.get('rows') or 0 for v in rs)} checks {dict(agg)} info {dict(inf)}")
    for v in rs:
        if not v['ok']: lines.append(f"  FAIL {v['project_id'][:120]} {v.get('checks')} {json.dumps(v.get('examples'))[:300]}")
open(f'{O}/summary.txt', 'w').write('\n'.join(lines) + '\n'); print('\n'.join(lines))
PYEOF
date -u +%FT%TZ > $O/started
systemctl reset-failed z3pkg-verify2 2>/dev/null
systemd-run --unit=z3pkg-verify2 --collect --working-directory=$K --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c "$PY $O/run.py $O > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 20; echo "started: $(systemctl is-active z3pkg-verify2)"; tail -n 3 $O/log.txt
