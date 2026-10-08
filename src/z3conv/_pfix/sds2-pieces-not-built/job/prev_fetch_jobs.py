#!/usr/bin/env python3
"""fetch_jobs.py OUTDIR ID [ID ...] -> materialize SDS2 job folders (same layout as the fleet worker)"""
import sys, os, json, gzip, re, subprocess, boto3
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
out = sys.argv[1]; ids = sys.argv[2:]
J = json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs.json')['Body'].read())
try:
    J += json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs_reconvert.json')['Body'].read())
except Exception:
    pass
byid = {j['id']: j for j in J}
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
def safe(s, n=60):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"
here = os.path.dirname(os.path.abspath(__file__))
for jid in ids:
    j = byid.get(jid)
    if not j:
        print(jid, 'NOT IN jobs.json'); continue
    name = safe(j.get('name') or 'job') + '_' + jid[:6]
    jd = os.path.join(out, name)
    if os.path.exists(os.path.join(jd, '.fetched')):
        print(jid, name, 'cached'); continue
    body = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
    try: body = gzip.decompress(body)
    except OSError: pass
    mf = json.loads(body)
    items = []
    for f in mf:
        parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
        items.append([f.get('key') or '', os.path.join(jd, *parts), f['size']])
    lst = os.path.join(out, name + '.fetch.json'); json.dump(items, open(lst, 'w'))
    r = subprocess.run([sys.executable, os.path.join(here, 'fetch.py'), lst, '48'], capture_output=True, text=True)
    print(jid, name, r.stdout.strip()[-300:], r.stderr.strip()[-300:])
    if '"n_errors": 0' in r.stdout:
        open(os.path.join(jd, '.fetched'), 'w').close()
