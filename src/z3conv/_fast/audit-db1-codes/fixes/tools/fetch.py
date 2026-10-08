"""fetch.py (box): DB1 sources + Tekla report siblings + every deployed DB1 output version, results, detail, grade results.
Run from /work/agentwork/audit-db1-codes."""
import json, os, sys, re, gzip, boto3, concurrent.futures as cf, botocore
B = 'bim-proprietary-data'; Z = 'cad-disk-extract/zenitude-data-3'
s3 = boto3.client('s3', config=botocore.config.Config(max_pool_connections=64, retries={'max_attempts': 8, 'mode': 'standard'}))
os.makedirs('state', exist_ok=True)
for k in ('_state/conv/db1/jobs.json', '_state/conv/db1/jobs_reconvert.json', '_state/conv/db1/redo.json', '_state/conv/index.jsonl.gz',
          '_state/conv_status.json'):
    s3.download_file(B, f'{Z}/{k}', 'state/' + k.rsplit('/', 1)[-1])
jobs = json.load(open('state/jobs.json')) + json.load(open('state/jobs_reconvert.json'))
_ids = {j['id'] for j in jobs}
jobs += [j for j in json.load(open('extra_jobs.json')) if j['id'] not in _ids]     # reconvert jobs already taken off the list (earlier copy)
json.dump(jobs, open('state/all_jobs.json', 'w'))


def ls(prefix):
    out = []
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        out += p.get('Contents', [])
    return out


tasks = []
for d, pre in (('out', f'{Z}/conversions/db1-step/'), ('res', f'{Z}/_state/conv/db1/results/'), ('det', f'{Z}/_state/conv/db1/detail/')):
    os.makedirs(d, exist_ok=True)
    for o in ls(pre):
        fn = o['Key'][len(pre):]
        if fn and '/' not in fn:
            tasks.append((o['Key'], os.path.join(d, fn), o['Size']))
os.makedirs('grade', exist_ok=True)
for j in jobs:
    tasks.append((f"{Z}/_state/conv/grade/results/db1-{j['id']}.json", f"grade/{j['id']}.json", None))
os.makedirs('src', exist_ok=True); os.makedirs('sib', exist_ok=True)
REP = re.compile(r'(bolt|part_list|part list|assembly|material|hot_|list).*\.(csv|xls|rpt|txt|lis)$|\.csv(\.rpt)?$', re.I)
sib_index = {}
for j in jobs:
    tasks.append((j['input_key'], f"src/{j['id']}.db1", j['size']))
    k = j['input_key']
    if '!' in k or '::' in k:
        continue                               # sibling files inside an archive: not individually on S3
    pre = k.rsplit('/', 1)[0] + '/'
    try:
        objs = [o for o in ls(pre) if '/' not in o['Key'][len(pre):]]
    except Exception:
        objs = []
    names = [o['Key'][len(pre):] for o in objs]
    sib_index[j['id']] = {'prefix': pre, 'files': names}
    for o in objs:
        fn = o['Key'][len(pre):]
        if REP.search(fn) and o['Size'] < 50 << 20:
            os.makedirs(f"sib/{j['id']}", exist_ok=True)
            tasks.append((o['Key'], f"sib/{j['id']}/{fn}", o['Size']))
json.dump(sib_index, open('state/sib_index.json', 'w'))


def get(t):
    key, dst, size = t
    if os.path.exists(dst) and (size is None or os.path.getsize(dst) == size):
        return 'cached'
    try:
        s3.download_file(B, key, dst + '.part'); os.replace(dst + '.part', dst); return 'ok'
    except Exception as e:
        return f'err {type(e).__name__}'


import collections
c = collections.Counter()
with cf.ThreadPoolExecutor(32) as ex:
    for r in ex.map(get, tasks):
        c[r.split()[0]] += 1
print(json.dumps({'tasks': len(tasks), 'result': dict(c), 'sib_models': len(sib_index)}))
