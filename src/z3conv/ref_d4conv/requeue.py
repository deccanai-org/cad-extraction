#!/usr/bin/env python3
"""Re-open conversion results for re-run (runtime convfleet-v4 workers read _control/conv/<pipe>/redo_ids.json every round).
  requeue.py PIPE --reason download_error [--reason ...]     re-run every result failed with that reason, finished before now
  requeue.py PIPE --ids ID [ID ...]                          re-run these job ids (results finished before now)
Existing entries / legacy ids (quote scan) are kept. Works with the bim profile (S3 get/put only)."""
import sys, json, time, argparse
import boto3
B = 'annotationprod'; Z4 = 'cad-disk-extract/zentitude-data-4'
ap = argparse.ArgumentParser(); ap.add_argument('pipe', choices=['ifc', 'db1', 'sds2'])
ap.add_argument('--reason', action='append', default=[]); ap.add_argument('--ids', nargs='*', default=[]); ap.add_argument('--why', default='')
a = ap.parse_args()
if not a.reason and not a.ids:
    sys.exit('give --reason and/or --ids')
s3 = boto3.client('s3', region_name='ap-south-1'); key = f'{Z4}/_control/conv/{a.pipe}/redo_ids.json'
try:
    d = json.loads(s3.get_object(Bucket=B, Key=key)['Body'].read())
    if not isinstance(d, dict): d = {}
except Exception:
    d = {}
before = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
e = {'before': before, 'why': a.why or 'requeue ' + ','.join(a.reason + a.ids[:3])}
if a.reason: e['reasons'] = a.reason
if a.ids: e['ids'] = a.ids
d.setdefault('entries', []).append(e); d['updated'] = before
s3.put_object(Bucket=B, Key=key, Body=json.dumps(d, indent=1).encode(), ContentType='application/json')
print('added', e, '->', key)
