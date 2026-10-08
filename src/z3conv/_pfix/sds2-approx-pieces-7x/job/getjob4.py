"""getjob4.py ID_PREFIX DEST -> materialize a data-3 SDS2 job from its files manifest (_state/conv/sds2/files/<fpc>.json.gz)
when the cached jobs.json does not list it; the folder name comes from the job's result record."""
import sys, os, json, gzip
from concurrent.futures import ThreadPoolExecutor
import boto3
jid, dest = sys.argv[1], sys.argv[2]
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; P = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/'
keys = [o['Key'] for o in s3.list_objects_v2(Bucket=B, Prefix=P + 'files/' + jid).get('Contents', [])]
assert len(keys) == 1, keys
fpc = os.path.basename(keys[0]).split('.')[0]
res = json.loads(s3.get_object(Bucket=B, Key=P + 'results/' + fpc[:24] + '.json')['Body'].read())
body = s3.get_object(Bucket=B, Key=keys[0])['Body'].read()
try:
    body = gzip.decompress(body)
except OSError:
    pass
mf = json.loads(body)
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s: ''.join(c if c.isalnum() or c in '-_.' else '_' for c in s)[:60]
jobdir = os.path.join(dest, safe(res['name']) + '_' + fpc[:6])


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
