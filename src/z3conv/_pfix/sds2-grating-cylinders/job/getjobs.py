#!/usr/bin/env python3
"""getjobs.py WD PY id1 id2 ... -> fetch SDS2 job folders (data-3 jobs.json) into WD/jobs/<name>_<id6>"""
import sys, os, json, gzip, subprocess, re, boto3
WD, PY = sys.argv[1], sys.argv[2]; ids = sys.argv[3:]
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
jp = os.path.join(WD, 'jobs.json')
if not os.path.exists(jp):
    open(jp, 'wb').write(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs.json')['Body'].read())
jobs = json.load(open(jp)); by = {j['id']: j for j in jobs}
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s, n=60: re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"
for i in ids:
    j = by.get(i)
    if j is None:
        print(i, 'NOT IN jobs.json', flush=True); continue
    name = safe(j.get('name') or 'job') + '_' + i[:6]
    jd = os.path.join(WD, 'jobs', name)
    if os.path.exists(os.path.join(jd, '.done')):
        print(i, name, 'cached', flush=True); continue
    body = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
    try: body = gzip.decompress(body)
    except OSError: pass
    mf = json.loads(body)
    items = []
    for f in mf:
        parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
        items.append([f.get('key') or '', os.path.join(jd, *parts), f['size']])
    lst = os.path.join(WD, 'fetch_' + i + '.json'); json.dump(items, open(lst, 'w'))
    out = subprocess.run([PY, os.path.join(WD, 'fetch.py'), lst, '16'], capture_output=True, text=True)
    print(i, name, out.stdout.strip()[-300:], out.stderr.strip()[-300:], flush=True)
    open(os.path.join(jd, '.done'), 'w').write('ok')
