#!/bin/bash
# Parallel replacement for stage 2's archive listing of the data-4 pkg-resolver (the single-process listing was GIL-bound: 2 h+).
# READ-ONLY: lists the Disk-1/2 extraction prefixes of every archive in res_hits.jsonl with 16 processes and writes
# /opt/pkgres4/work/listings.pkl (same structure the resolver's stage 2 caches: {archive: [(prefix, [(key, size, etag)])]}).
# Then stops the slow unit z3pkgres4 and restarts the resolver at stages 2-4 (stage 2 reuses listings.pkl).
# Idempotent: first call starts unit z3pkgres4-list; later calls print progress.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgres4
if systemctl is-active -q z3pkgres4-list; then echo "listing running since $(cat $D/list_started)"; tail -n 3 $D/list_log.txt; exit 0; fi
if [ -f $D/list_finished ]; then echo "listing finished $(cat $D/list_finished)"; tail -n 3 $D/list_log.txt; systemctl is-active z3pkgres4; tail -n 4 $D/log.txt; exit 0; fi
cat > $D/listpar.py <<'PYEOF'
import json, re, hashlib, pickle, os, sys, time
from multiprocessing import Pool
import boto3
from botocore.config import Config
B = 'bim-proprietary-data'; W = '/opt/pkgres4/work'
def sc(v):
    v = re.sub(r"[^A-Za-z0-9._!+\-]+", "_", v)
    return re.sub(r"_+", "_", v).strip("_") or "_"
def _san(s): return re.sub(r'[^A-Za-z0-9._-]+', '_', s)
def prefixes(source_key):
    disk, rel = source_key.split('/', 1); h12 = hashlib.sha256(source_key.encode()).hexdigest()[:12]; out = []
    for flat in (sc(rel)[:240], _san(rel)):
        for p in (f'cad-disk-extract/{disk}/{flat}-{h12}/', f'cad-disk-extract/{disk}/{flat}/'):
            if p not in out: out.append(p)
    return out
S3 = None
def init():
    global S3
    S3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=8, retries={'max_attempts': 10, 'mode': 'standard'}))
def do_list(a):
    got = []
    for p in prefixes(a):
        ks = []
        for attempt in range(5):
            try:
                ks = []
                for pg in S3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=p):
                    ks += [(o['Key'], o['Size'], o['ETag'].strip('"')) for o in pg.get('Contents', [])]
                break
            except Exception as e:
                time.sleep(5 * (attempt + 1))
        if ks: got.append((p, ks))
    return a, got
if __name__ == '__main__':
    archives = sorted({r['source_key'] for r in (json.loads(l) for l in open(f'{W}/res_hits.jsonl')) if r['hits']})
    print('archives to list', len(archives), flush=True)
    listing = {}; t = time.time()
    with Pool(16, initializer=init) as pool:
        for i, (a, got) in enumerate(pool.imap_unordered(do_list, archives, chunksize=1), 1):
            listing[a] = got
            if i % 50 == 0: print(i, 'archives', sum(len(ks) for g in listing.values() for _, ks in g), 'keys', round(time.time() - t), 's', flush=True)
    pickle.dump(listing, open(f'{W}/listings.pkl.tmp', 'wb')); os.replace(f'{W}/listings.pkl.tmp', f'{W}/listings.pkl')
    print('DONE archives', len(listing), 'keys', sum(len(ks) for g in listing.values() for _, ks in g), 'without prefix', sum(1 for a in listing if not listing[a]), flush=True)
PYEOF
date -u +%FT%TZ > $D/list_started
systemctl reset-failed z3pkgres4-list 2>/dev/null
systemd-run --unit=z3pkgres4-list --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/conv/env/bin/python $D/listpar.py > $D/list_log.txt 2>&1 && test -s $D/work/listings.pkl && { systemctl stop z3pkgres4; sleep 3; rm -f $D/finished; date -u +%FT%TZ > $D/started; systemctl reset-failed z3pkgres4; systemd-run --unit=z3pkgres4 --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c '/opt/conv/env/bin/python $D/run.py 234 > $D/log.txt 2>&1; echo rc=\$? >> $D/log.txt; date -u +%FT%TZ > $D/finished'; }; date -u +%FT%TZ > $D/list_finished"
sleep 30; echo "started: $(systemctl is-active z3pkgres4-list)"; tail -n 3 $D/list_log.txt
