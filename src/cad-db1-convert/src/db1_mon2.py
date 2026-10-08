"""progress of the re-run: only results produced by the current worker CODE count."""
import boto3, json, collections, time, datetime as dt, concurrent.futures as cf, os
CODE = 'db1-2026-09-25g'
_KEEP_NONOK = {'empty_model','no_member_layout','no_resolvable_members','bad_output','deferred_layout'}
KEEP = {c: _KEEP_NONOK for c in ('db1-2026-09-25b','db1-2026-09-25c','db1-2026-09-25d','db1-2026-09-25e')}
KEEP['db1-2026-09-25f'] = _KEEP_NONOK | {'ok','suspect_orientation','suspect_attr_link','convert_error'}
def kept(r):
    return r.get('status') in KEEP.get(r.get('code'), ())
s = boto3.Session().client('s3', region_name='ap-south-1'); B = 'annotationprod'; ST = 'cad-disk-extract/_state/db1-v2/'
keys = [o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=ST + 'results/') for o in p.get('Contents', [])]
def get(k):
    for _ in range(4):
        try: return json.loads(s.get_object(Bucket=B, Key=k)['Body'].read())
        except Exception: time.sleep(1)
with cf.ThreadPoolExecutor(64) as ex: R = [r for r in ex.map(get, keys) if r]
new = [r for r in R if r.get('code') == CODE or kept(r)]
stale = [r for r in R if r.get('code') in KEEP and r not in new]
json.dump(new, open('db1_results_v2.json', 'w'), default=str)
J = json.load(open('db1_jobs.json')); J = J['jobs'] if isinstance(J, dict) else J
todo = len([j for j in J if j['engine'] != 'None'])
st = collections.Counter(r['status'] for r in new)
print(time.strftime('%H:%M:%SZ', time.gmtime()), f'final-code results {len(new)}/{todo}', dict(st), f'(results to redo on g: {len(stale)})')
by = collections.defaultdict(collections.Counter)
for r in new: by[r['engine']][r['status']] += 1
for e, c in sorted(by.items()): print('   ', e, dict(c))
ok = [r for r in new if r['status'] == 'ok']
print('   ok files: members', sum(r['convert'].get('members', 0) for r in ok), 'written', sum(r['convert'].get('written', 0) for r in ok))
now = dt.datetime.now(dt.timezone.utc); live = 0; run = 0
for o in s.list_objects_v2(Bucket=B, Prefix=ST + 'hosts/').get('Contents', []):
    if o['Key'].endswith('.json') and 'fatal' not in o['Key'] and (now - o['LastModified']).total_seconds() < 300:
        h = get(o['Key']);
        if h and h.get('code') in (CODE, 'db1-2026-09-25f'): live += 1; run += len(h.get('running', []))
print(f'   live hosts on new code: {live}, jobs running: {run}')
