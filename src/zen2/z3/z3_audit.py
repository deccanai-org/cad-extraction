"""Data-3 final object audit (runs on the coordinator with the instance role).
For every archive job: list every object under its extracted/ prefix and stream its manifest, then check
  - every manifest entry stored in this job (no dedup) has its object with the right size  -> stored_ok / stored_missing
  - entries a re-run recorded as dedup 'disk' whose own object is present (stored by an earlier attempt of the same job)
  - objects under the prefix that no manifest entry references (orphans)
Writes _state/stats/audit_objects.json (summary + per-job problems) to the data-3 work area."""
import boto3, json, gzip, sys, time, collections, os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from botocore.config import Config
B = 'bim-proprietary-data'; ROOT = 'cad-disk-extract/zenitude-data-3'; STRIP = 'Zenitude-data-3/'
CTL_B = 'annotationprod'; JOBS = 'cad-disk-extract/_control/move/z3/jobs.json'
_c = {}
def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'}, max_pool_connections=64))
    return _c['c']

def list_flat(prefix, delim=False):
    out, subs = {}, []
    kw = dict(Bucket=B, Prefix=prefix)
    if delim: kw['Delimiter'] = '/'
    for pg in s3().get_paginator('list_objects_v2').paginate(**kw):
        for o in pg.get('Contents', []): out[o['Key']] = o['Size']
        subs += [p['Prefix'] for p in pg.get('CommonPrefixes', [])]
    return out, subs

def list_all(prefix):
    """All objects under prefix; big trees are listed per sub-folder in parallel (split up to 3 levels)."""
    objs, todo = {}, [prefix]
    for _ in range(3):
        nxt = []
        for p in todo:
            o, subs = list_flat(p, delim=True); objs.update(o); nxt += subs
        todo = nxt
        if len(todo) >= 32 or not todo: break
    with ThreadPoolExecutor(32) as ex:
        for o, _ in ex.map(list_flat, todo): objs.update(o)
    return objs

def audit(job):
    jid, key = job['id'], job['key']
    prefix = f"{ROOT}/extracted/{key[len(STRIP):].replace('/', '_')}"
    S = list_all(prefix + '/')
    r = {'id': jid, 'path': key[len(STRIP):], 'objects': len(S), 'object_bytes': sum(S.values())}
    try:
        body = s3().get_object(Bucket=B, Key=f'{ROOT}/_state/manifests/{jid}.jsonl.gz')['Body']
    except Exception as e:
        r['manifest'] = False; r['orphans'] = len(S); return r
    c = collections.Counter(); b = collections.Counter(); ref = set(); missing = []
    with gzip.GzipFile(fileobj=body) as f:
        for line in f:
            if not line.strip(): continue
            e = json.loads(line); k = e.get('key') or ''; d = e.get('dedup'); sz = e.get('size') or 0
            c['entries'] += 1
            if not d:
                if S.get(k) == sz: c['stored_ok'] += 1; b['stored_ok'] += sz; ref.add(k)
                else:
                    c['stored_missing'] += 1
                    if len(missing) < 20: missing.append([k, sz, S.get(k)])
            else:
                own = f"{prefix}/{e['path']}"
                if d == 'disk' and S.get(own) == sz:
                    c['disk_but_own_object'] += 1; b['disk_but_own_object'] += sz; ref.add(own)
                else:
                    c['dedup_' + str(d)] += 1; b['dedup_' + str(d)] += sz
    orph = [k for k in S if k not in ref]
    r.update(manifest=True, counts=dict(c), bytes=dict(b), orphans=len(orph), orphan_bytes=sum(S[k] for k in orph),
             orphan_examples=orph[:5], missing_examples=missing)
    return r

CACHE = os.environ.get('AUDIT_CACHE', '/opt/z3audit/rows')

def audit_cached(job):
    """Re-use a job's audit row while its manifest is unchanged (ETag); otherwise audit it again."""
    os.makedirs(CACHE, exist_ok=True)
    try:
        et = s3().head_object(Bucket=B, Key=f"{ROOT}/_state/manifests/{job['id']}.jsonl.gz")['ETag']
    except Exception:
        et = None
    cf = os.path.join(CACHE, job['id'] + '.json')
    if et and os.path.exists(cf):
        r = json.load(open(cf))
        if r.get('etag') == et:
            return r
    r = audit(job); r['etag'] = et
    if et:
        json.dump(r, open(cf + '.tmp', 'w')); os.replace(cf + '.tmp', cf)
    return r

if __name__ == '__main__':
    jobs = json.loads(s3().get_object(Bucket=CTL_B, Key=JOBS)['Body'].read())
    jobs = [j for j in (jobs['jobs'] if isinstance(jobs, dict) else jobs) if j.get('type') != 'loose']
    if len(sys.argv) > 1: jobs = [j for j in jobs if j['id'] in sys.argv[1:]]
    jobs.sort(key=lambda j: -(j.get('size') or 0))
    t0 = time.time(); rows = []
    with ProcessPoolExecutor(int(os.environ.get('AUDIT_PROCS', '20'))) as ex:
        for i, r in enumerate(ex.map(audit_cached, jobs, chunksize=1)):
            rows.append(r)
            if i % 200 == 0: print(time.strftime('%H:%M:%S'), i, len(jobs), flush=True)
    T = collections.Counter(); TB = collections.Counter()
    for r in rows:
        T['objects'] += r['objects']; TB['objects'] += r['object_bytes']; T['orphans'] += r.get('orphans', 0); TB['orphans'] += r.get('orphan_bytes', 0)
        for k, v in (r.get('counts') or {}).items(): T[k] += v
        for k, v in (r.get('bytes') or {}).items(): TB[k] += v
        T['no_manifest'] += 0 if r.get('manifest') else 1
    problems = [r for r in rows if not r.get('manifest') or (r.get('counts') or {}).get('stored_missing') or r.get('orphans')]
    out = {'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'archive_jobs': len(rows), 'seconds': round(time.time() - t0),
           'totals': dict(T), 'total_bytes': dict(TB),
           'rule': 'objects = every S3 object under each archive extracted/ prefix; stored_ok = manifest entries stored by that job whose object exists with the same size; '
                   'disk_but_own_object = re-run entries recorded as dedup disk although the job stored its own copy earlier (counted as stored); orphans = objects no manifest entry references',
           'problem_jobs': problems[:300], 'problem_job_count': len(problems)}
    body = json.dumps(out, indent=1).encode()
    if len(sys.argv) > 1: print(json.dumps(out)[:3000])
    else: s3().put_object(Bucket=B, Key=f'{ROOT}/_state/stats/audit_objects.json', Body=body)
    print('done', json.dumps({k: out[k] for k in ('archive_jobs', 'seconds', 'totals', 'problem_job_count')}), flush=True)
