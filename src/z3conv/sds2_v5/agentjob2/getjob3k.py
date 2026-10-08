"""fetch a data-3 SDS2 job by files-manifest key (bim profile). usage: getjob3k.py <files_key> <dest dir> <name>"""
import sys, os, json, gzip
from concurrent.futures import ThreadPoolExecutor
import boto3
key, dest, name = sys.argv[1:4]
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
body = s3.get_object(Bucket=B, Key=key)['Body'].read()
try: body = gzip.decompress(body)
except OSError: pass
mf = json.loads(body)
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
jobdir = os.path.join(dest, name)
def one(f):
    parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
    path = os.path.join(jobdir, *parts); os.makedirs(os.path.dirname(path), exist_ok=True)
    if not f.get('key'): open(path, 'wb').close(); return
    open(path, 'wb').write(s3.get_object(Bucket=B, Key=f['key'])['Body'].read())
with ThreadPoolExecutor(16) as ex: list(ex.map(one, mf))
print(jobdir)
