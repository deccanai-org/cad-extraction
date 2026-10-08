#!/usr/bin/env python3
"""pfetch.py OUTDIR ID NAME SIDS -> partial SDS2 job folder: main/job_mtrl, subm/subm_idx and the listed piece files only
(SIDS = comma list or @file). Prints the folder name last."""
import sys, os, json, gzip, re, boto3
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
out, jid, nm, sids = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sids = set(open(sids[1:]).read().split()) if sids.startswith('@') else set(sids.split(','))
cache = os.path.join(out, '_jobs.json')
if not os.path.exists(cache):
    J = json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs.json')['Body'].read())
    try:
        J += json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs_reconvert.json')['Body'].read())
    except Exception:
        pass
    tmp = cache + f'.{os.getpid()}'; json.dump(J, open(tmp, 'w')); os.replace(tmp, cache)
byid = {j['id']: j for j in json.load(open(cache))}
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s, n=60: re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"
j = byid.get(jid)
if j is None:
    r_ = s3.list_objects_v2(Bucket=B, Prefix='cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/' + jid)
    j = dict(id=jid, name=nm, files_key=r_['Contents'][0]['Key'])
name = safe(j.get('name') or nm or 'job') + '_' + jid[:6]
jd = os.path.join(out, name)
body = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
try: body = gzip.decompress(body)
except OSError: pass
items = []
for f in json.loads(body):
    parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
    rel = '/'.join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    want = rel in ('main/job_mtrl', 'subm/subm_idx') or (len(parts) >= 2 and parts[-2] == 'subm' and parts[-1] in sids)
    if want:
        items.append([f.get('key') or '', os.path.join(jd, *parts), f['size']])
# piece files may sit under a job root prefix: keep the layout of the full fetch (paths as listed)
lst = os.path.join(out, name + '.pfetch.json'); json.dump(items, open(lst, 'w'))
import subprocess
r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fetch.py'), lst, '16'], capture_output=True, text=True)
print(jid, name, len(items), r.stdout.strip()[-200:], file=sys.stderr)
print(name)
