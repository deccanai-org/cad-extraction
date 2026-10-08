#!/bin/bash
/opt/conv/env/bin/python - <<'PY'
import boto3, json, collections, re
from concurrent.futures import ThreadPoolExecutor
s3=boto3.client('s3',region_name='ap-south-1')
B='bim-proprietary-data'; P='cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/'
V=json.loads(s3.get_object(Bucket=B,Key='cad-disk-extract/zenitude-data-3/_state/conv/scan/sds2_versions.json')['Body'].read())
ks=[]; tok=None
while True:
    kw=dict(Bucket=B,Prefix=P)
    if tok: kw['ContinuationToken']=tok
    r=s3.list_objects_v2(**kw); ks+=[o['Key'] for o in r.get('Contents',[])]
    if not r.get('IsTruncated'): break
    tok=r['NextContinuationToken']
def one(k):
    d=json.loads(s3.get_object(Bucket=B,Key=k)['Body'].read())
    if d.get('reason')!='no_members_to_calibrate': return None
    lt=d.get('log_tail') or ''
    kind='empty_no_member_files' if 'empty job, no member files' in lt else ('valueerror_calibrate' if 'too few members to calibrate' in lt else 'other')
    m=d.get('manifest') or {}
    return (d['id'], V.get(d['id']), (d.get('converter') or {}).get('label') or d.get('code','')[8:13], kind, (m.get('empty_job_proof') or {}).get('subm_files'), d.get('n_files'), (d.get('paths_sample') or [''])[0][-70:])
res=[x for x in ThreadPoolExecutor(32).map(one, ks) if x]
c=collections.Counter((x[2],x[3]) for x in res)
print(len(res), sorted(c.items()))
for x in res:
    if x[3]=='valueerror_calibrate' and not x[2].startswith('v5-') and x[2]!='v5': print(x)
PY
