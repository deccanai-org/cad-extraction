import sys, os, json, gzip
from concurrent.futures import ThreadPoolExecutor
import boto3
jid, dest = sys.argv[1], sys.argv[2]
jobs = {j['id']: j for j in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs.json')))}
job = next(j for k, j in jobs.items() if k.startswith(jid))
s3 = boto3.client('s3', region_name='ap-south-1')
def _get(key):
    # data-4 objects moved from annotationprod to bim-proprietary-data (same keys)
    for b in ('bim-proprietary-data', 'annotationprod'):
        try:
            return s3.get_object(Bucket=b, Key=key)['Body'].read()
        except s3.exceptions.NoSuchKey:
            continue
    raise KeyError(key)
body = _get(job['files_key'])
try:
    body = gzip.decompress(body)
except OSError:
    pass
mf = json.loads(body)
root = job.get('job_root') or ''
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s: ''.join(c if c.isalnum() or c in '-_.' else '_' for c in s)[:60]
name = safe(os.path.basename(root) if root else (job.get('name') or 'job')) + '_' + job['id'][:6]
jobdir = os.path.join(dest, name)
pre = len(root) + 1 if root else 0


def one(f):
    rel = f['p'].replace('\\', '/')[pre:]
    parts = [p.lower() if p.lower() in CANON else p for p in rel.split('/') if p]
    path = os.path.join(jobdir, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not f.get('key'):
        open(path, 'wb').close(); return
    open(path, 'wb').write(_get(f['key']))


with ThreadPoolExecutor(16) as ex:
    list(ex.map(one, mf))
print(jobdir)
