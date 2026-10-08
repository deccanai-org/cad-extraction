#!/usr/bin/env python3
"""Aggregate the Zentitude-data-4 conversion pipelines into _state/conv_status.json (read by the live page).
Static per-pipeline settings (fanout_ready, user-data key, recommended instances, notes) come from
_control/conv/status_config.json; counters from _control/conv/<pipe>/jobs.json + _state/conv/<pipe>/{results,claims,hosts}.
usage: python3 conv_status.py [--loop 120]"""
import json, time, sys, collections, argparse
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'annotationprod'; Z4 = 'cad-disk-extract/zentitude-data-4'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 8, 'mode': 'adaptive'}))
CACHE = {}          # key -> (etag, compact result)
JOBS = {}           # pipe -> (etag, n, bytes, ids)


def lst(prefix):
    out = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        out += page.get('Contents', [])
    return out


def getj(key):
    try:
        return json.loads(s3.get_object(Bucket=B, Key=key)['Body'].read())
    except Exception:
        return None


def compact(r):
    st = r.get('step') or {}
    v = r.get('validate') or {}
    return {'status': r.get('status'), 'reason': r.get('reason'), 'bytes': st.get('bytes') or r.get('out_bytes') or 0,
            'files': st.get('files') or (1 if r.get('status') == 'ok' else 0), 'validated': bool(v.get('validated') or r.get('validated')),
            'fix': r.get('input_fix'), 'excluded': len(r.get('excluded_elements') or [])}


def load(o):
    k = o['Key']
    c = CACHE.get(k)
    if c and c[0] == o['ETag']:
        return c[1]
    r = getj(k)
    if r is None:
        return None
    v = compact(r); CACHE[k] = (o['ETag'], v)
    return v


def pipe_stats(pipe, cfg):
    ST = f'{Z4}/_state/conv/{pipe}'
    try:
        h = s3.head_object(Bucket=B, Key=f'{Z4}/_control/conv/{pipe}/jobs.json')
        if JOBS.get(pipe, (None,))[0] != h['ETag']:
            jobs = getj(f'{Z4}/_control/conv/{pipe}/jobs.json') or []
            JOBS[pipe] = (h['ETag'], len(jobs), sum(j.get('size') or 0 for j in jobs), {j['id'] for j in jobs})
        _, n, nbytes, ids = JOBS[pipe]
    except Exception:
        n, nbytes, ids = 0, 0, set()
    res = [o for o in lst(f'{ST}/results/') if o['Key'].endswith('.json')]
    with ThreadPoolExecutor(48) as ex:
        rs = list(ex.map(load, res))
    rs = [(o, r) for o, r in zip(res, rs) if r and o['Key'].rsplit('/', 1)[-1][:-5] in ids]
    ok = [r for o, r in rs if r['status'] == 'ok']
    fails = collections.Counter(r['reason'] or 'unknown' for o, r in rs if r['status'] != 'ok')
    now = time.time()
    claims = lst(f'{ST}/claims/')
    fresh = sum(1 for o in claims if now - o['LastModified'].timestamp() < 1500)
    hosts = lst(f'{ST}/hosts/')
    live = [o for o in hosts if now - o['LastModified'].timestamp() < 300]
    fixes = collections.Counter()
    for r in ok:
        f = r.get('fix')
        for x in (f if isinstance(f, list) else ([f] if f else [])):
            fixes[x] += 1
    out = {'jobs': n, 'jobs_input_bytes': nbytes, 'done': len(rs), 'ok': len(ok), 'failed': len(rs) - len(ok),
           'failed_by_reason': dict(fails.most_common()), 'in_flight': fresh, 'pending': max(0, n - len(rs)),
           'step_files': sum(r['files'] for r in ok), 'step_bytes': sum(r['bytes'] for r in ok),
           'validated': sum(1 for r in ok if r['validated']), 'input_fixes_ok': dict(fixes),
           'ok_with_excluded_elements': sum(1 for r in ok if r['excluded']), 'worker_processes_live': len(live),
           'pct_done': round(100.0 * len(rs) / n, 2) if n else 0.0}
    out.update(cfg or {})
    return out


def once():
    cfg = getj(f'{Z4}/_control/conv/status_config.json') or {}
    doc = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'source': 'Zentitude-data-4',
           'rule': 'one job per distinct new content (sha256 not stored by Disk-1/2); disk12 duplicates were converted in the Disk-1/2 run',
           'pipelines': {}}
    for pipe in ('ifc', 'db1', 'sds2'):
        doc['pipelines'][pipe] = pipe_stats(pipe, (cfg.get('pipelines') or {}).get(pipe))
        doc[pipe] = doc['pipelines'][pipe]          # flat alias
    for k, v in cfg.items():
        if k != 'pipelines':
            doc[k] = v
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/conv_status.json', Body=json.dumps(doc, indent=1, default=str).encode(),
                  ContentType='application/json', CacheControl='no-cache')
    return doc


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--loop', type=int, default=0); a = ap.parse_args()
    while True:
        try:
            d = once()
            print(d['updated'], {p: (d[p]['done'], d[p]['jobs'], d[p]['ok']) for p in ('ifc', 'db1', 'sds2')}, flush=True)
        except Exception as e:
            print('error', type(e).__name__, str(e)[:300], flush=True)
        if not a.loop:
            break
        time.sleep(a.loop)
