import sys, os, json, gzip
from concurrent.futures import ThreadPoolExecutor
import boto3
jid, dest = sys.argv[1], sys.argv[2]
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
here = os.path.dirname(os.path.abspath(__file__))
jl = os.path.join(here, 'd3jobs.json')
if not os.path.exists(jl):
    open(jl, 'wb').write(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs.json')['Body'].read())
job = next(j for j in json.load(open(jl)) if j['id'].startswith(jid))
body = s3.get_object(Bucket=B, Key=job['files_key'])['Body'].read()
try:
    body = gzip.decompress(body)
except OSError:
    pass
mf = json.loads(body)
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s: ''.join(c if c.isalnum() or c in '-_.' else '_' for c in s)[:60]
jobdir = os.path.join(dest, safe(job['name']) + '_' + job['id'][:6])


def one(f):
    parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
    path = os.path.join(jobdir, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not f.get('key'):
        open(path, 'wb').close(); return
    open(path, 'wb').write(s3.get_object(Bucket=B, Key=f['key'])['Body'].read())


with ThreadPoolExecutor(16) as ex:
    list(ex.map(one, mf))
print(jobdir)
