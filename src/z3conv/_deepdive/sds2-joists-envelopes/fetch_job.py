"""fetch an SDS2 job's main/ mem/ subm/ files from the bim bucket (read only) into jobs/<name>/"""
import sys, json, gzip, os, boto3, concurrent.futures as cf
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
files_json, dest = sys.argv[1], sys.argv[2]
only = sys.argv[3].split(',') if len(sys.argv) > 3 else None
d = json.loads(gzip.open(files_json).read())
todo = []
for f in d:
    p = f['p'].replace('\\', '/')
    parts = [x.lower() if x.lower() in ('main', 'mem', 'subm') else x for x in p.split('/') if x]
    if only and not any(p.lower().startswith(o) for o in only):
        continue
    out = os.path.join(dest, *parts)
    if os.path.exists(out) and os.path.getsize(out) == f['size']:
        continue
    if not f.get('key'):
        continue
    todo.append((f['key'], out))
def get(a):
    k, out = a
    os.makedirs(os.path.dirname(out), exist_ok=True)
    s3.download_file(B, k, out)
with cf.ThreadPoolExecutor(32) as ex:
    list(ex.map(get, todo))
print('fetched', len(todo))
