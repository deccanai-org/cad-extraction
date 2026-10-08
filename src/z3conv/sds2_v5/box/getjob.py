#!/usr/bin/env python3
"""Materialise one data-4 SDS/2 job folder (main/ mem/ subm/) exactly as the fleet worker does.
usage: getjob.py JOB_ID DEST_ROOT  -> prints the job folder path"""
import sys, os, json, gzip, subprocess
import boto3
sys.path.insert(0, '/opt/conv/kit/sds2')
jid, dest = sys.argv[1], sys.argv[2]
jobs = {j['id']: j for j in json.load(open('/opt/conv/kit/sds2/jobs.json'))}
job = jobs[jid]
s3 = boto3.client('s3', region_name='ap-south-1')
body = s3.get_object(Bucket='annotationprod', Key=job['files_key'])['Body'].read()
try: body = gzip.decompress(body)
except OSError: pass
mf = json.loads(body)
root = job.get('job_root') or ''
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
safe = lambda s: ''.join(c if c.isalnum() or c in '-_.' else '_' for c in s)[:60]
name = safe(os.path.basename(root) if root else (job.get('name') or 'job')) + '_' + jid[:6]
jobdir = os.path.join(dest, name)
pre = len(root) + 1 if root else 0
items = []
for f in mf:
    rel = f['p'].replace('\\', '/')[pre:]
    parts = [p.lower() if p.lower() in CANON else p for p in rel.split('/') if p]
    items.append([f.get('key'), os.path.join(jobdir, *parts), f['size']])
lst = os.path.join(dest, f'{jid}.fetch.json'); json.dump(items, open(lst, 'w'))
r = subprocess.run(['/opt/conv/sds2env/bin/python', '/opt/conv/kit/sds2/fetch.py', lst, '32'], capture_output=True, text=True)
sys.stderr.write(r.stdout[-300:])
print(jobdir)
