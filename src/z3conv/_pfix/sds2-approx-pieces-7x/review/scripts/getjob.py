"""getjob.py ID_PREFIX DEST -> materialise a data-3 SDS2 job (jobs.json files_key, else files/<fpc>.json.gz manifest)."""
import sys, os, json, gzip
from concurrent.futures import ThreadPoolExecutor
import boto3
jid, dest = sys.argv[1], sys.argv[2]
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; P = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/'
here = os.path.dirname(os.path.abspath(__file__)); jl = os.path.join(here, 'd3jobs.json')
if not os.path.exists(jl):
    open(jl, 'wb').write(s3.get_object(Bucket=B, Key=P + 'jobs.json')['Body'].read())
job = next((j for j in json.load(open(jl)) if j['id'].startswith(jid)), None)
if job:
    key, name, fid = job['files_key'], job['name'], job['id']
else:
    keys = [o['Key'] for o in s3.list_objects_v2(Bucket=B, Prefix=P + 'files/' + jid).get('Contents', [])]
    assert len(keys) == 1, keys
    key = keys[0]; fid = os.path.basename(key).split('.')[0]
    name = json.loads(s3.get_object(Bucket=B, Key=P + 'results/' + fid[:24] + '.json')['Body'].read())['name']
body = s3.get_object(Bucket=B, Key=key)['Body'].read()
try:
    body = gzip.decompress(body)
except OSError:
    pass
mf = json.loads(body)
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s: ''.join(c if c.isalnum() or c in '-_.' else '_' for c in s)[:60]
jobdir = os.path.join(dest, safe(name) + '_' + fid[:6])
def one(f):
    parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
    path = os.path.join(jobdir, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not f.get('key'):
        open(path, 'wb').close(); return
    open(path, 'wb').write(s3.get_object(Bucket=B, Key=f['key'])['Body'].read())
with ThreadPoolExecutor(8) as ex:
    list(ex.map(one, mf))
print(jobdir)
