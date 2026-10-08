#!/usr/bin/env python3
"""merge_split.py [--apply] : SDS2 loose-folder jobs that the scan split into one job per subfolder (main/ and mem/ as separate
'archives' with the same job_root, each incomplete) -> one merged job per job_root with the union of their file lists.
Writes (with --apply, instance role): _state/conv/sds2/files/<fpc>.json.gz and _state/conv/sds2/jobs_merged.json (merged jobs, each
with merged_from = the halves). The index lists the merged job and drops the halves; workers read jobs_merged.json as an extra list."""
import boto3, json, gzip, hashlib, sys, collections
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1') if '--apply' in sys.argv else boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2'


def getj(k):
    b = s3.get_object(Bucket=B, Key=k)['Body'].read()
    return json.loads(gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b)


jobs = getj(f'{ST}/jobs.json'); jobs = jobs['jobs'] if isinstance(jobs, dict) else jobs
grp = collections.defaultdict(list)
for j in jobs:
    if j.get('complete_layout') is False and j.get('job_root'):
        grp[j['job_root']].append(j)
merged = []; skipped = collections.Counter()
for root, js in sorted(grp.items()):
    if len(js) < 2:
        skipped['single_half'] += 1; continue
    with ThreadPoolExecutor(8) as ex:
        lists = list(ex.map(lambda j: getj(j['files_key']), js))
    files = {}
    for fl in lists:
        for f in fl:
            files.setdefault(f['p'], f)
    ps = set(files)
    if 'main/job_mtrl' not in ps or 'mem/mem_idx' not in ps:
        skipped['still_incomplete'] += 1; continue
    fl = [files[p] for p in sorted(files)]
    fpc = hashlib.sha256('\n'.join(f"{f['p']}\t{f['sha256']}" for f in fl).encode()).hexdigest()
    base = max(js, key=lambda j: 1 if j.get('jsetup_sha256') else 0)
    mj = dict(base, id=fpc[:24], fpc=fpc, files_key=f'{ST}/files/{fpc}.json.gz', n_files=len(fl),
              size=sum(f['size'] for f in fl), model_bytes=sum(f['size'] for f in fl), complete_layout=True,
              archive=root, merged_from=[j['id'] for j in js], paths=sorted({p for j in js for p in (j.get('paths') or [])}),
              n_paths=len({p for j in js for p in (j.get('paths') or [])}),
              jsetup_sha256=next((j['jsetup_sha256'] for j in js if j.get('jsetup_sha256')), None))
    merged.append((mj, fl))
print('split groups', sum(1 for v in grp.values() if len(v) >= 2), 'merged', len(merged), dict(skipped))
for mj, fl in merged[:20]:
    print(' ', mj['id'], mj['name'], 'files', mj['n_files'], 'MB', mj['model_bytes'] >> 20, 'from', mj['merged_from'])
if '--apply' in sys.argv:
    for mj, fl in merged:
        s3.put_object(Bucket=B, Key=mj['files_key'], Body=gzip.compress(json.dumps(fl).encode()), ContentType='application/json')
    s3.put_object(Bucket=B, Key=f'{ST}/jobs_merged.json', Body=json.dumps([m for m, _ in merged]).encode(), ContentType='application/json')
    print('written', len(merged))
