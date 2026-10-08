"""Fetch (read-only) an SDS2 data-3 job's model files from the bim bucket into <dest>/<name>/ (main/ mem/ subm/ lower-cased).
usage: fetch_job.py <job id> <dest> [prefix,prefix,...]   prefixes match the lower-cased in-job path, e.g. main/,mem/,subm/subm_idx,subm/904
Writes nothing to S3."""
import sys, json, gzip, os, boto3, concurrent.futures as cf
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
HERE = os.path.dirname(os.path.abspath(__file__))
jid, dest = sys.argv[1], sys.argv[2]
only = [o.lower() for o in sys.argv[3].split(',')] if len(sys.argv) > 3 and sys.argv[3] else None
jobs = json.load(open(os.path.join(HERE, '..', 'data', 'jobs.json')))
job = next((j for j in jobs if j['id'].startswith(jid)), None)
if job is None:   # reused job (graded, not converted): files list by converter-input fingerprint; name from argv[4]
    job = {'id': jid, 'name': sys.argv[4] if len(sys.argv) > 4 else jid[:8],
           'files_key': f'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/{jid}.json.gz'}
body = s3.get_object(Bucket=B, Key=job['files_key'])['Body'].read()
try: body = gzip.decompress(body)
except OSError: pass
files = json.loads(body)
root = os.path.join(dest, job['name'].replace(' ', '_') + '_' + job['id'][:6])
todo = []
for f in files:
    p = f['p'].replace('\\', '/')
    parts = [x.lower() if x.lower() in ('main', 'mem', 'subm') else x for x in p.split('/') if x]
    rel = '/'.join(parts).lower()
    if only and not any(rel == o or (o.endswith('/') and rel.startswith(o)) for o in only):
        continue
    out = os.path.join(root, *parts)
    if f['size'] == 0:
        os.makedirs(os.path.dirname(out), exist_ok=True); open(out, 'wb').close(); continue
    if os.path.exists(out) and os.path.getsize(out) == f['size']:
        continue
    if not f.get('key'):
        print('no key', p); continue
    todo.append((f['key'], out))
def get(a):
    k, out = a
    os.makedirs(os.path.dirname(out), exist_ok=True)
    s3.download_file(B, k, out)
with cf.ThreadPoolExecutor(32) as ex:
    list(ex.map(get, todo))
print(root, 'fetched', len(todo), 'of', len(files))
