#!/bin/bash
/opt/conv/env/bin/python - <<'PY'
import boto3, json, datetime, collections
from concurrent.futures import ThreadPoolExecutor
s3=boto3.client('s3',region_name='ap-south-1')
B='bim-proprietary-data'; P='cad-disk-extract/zenitude-data-3/_state/conv/sds2/claims/'
ks=[]; tok=None
while True:
    kw=dict(Bucket=B,Prefix=P)
    if tok: kw['ContinuationToken']=tok
    r=s3.list_objects_v2(**kw); ks+= [(o['Key'],o['LastModified']) for o in r.get('Contents',[])]
    if not r.get('IsTruncated'): break
    tok=r['NextContinuationToken']
now=datetime.datetime.now(datetime.timezone.utc)
def one(k):
    try: d=json.loads(s3.get_object(Bucket=B,Key=k[0])['Body'].read())
    except Exception: d={}
    return d.get('code'), (now-k[1]).total_seconds()/60
res=list(ThreadPoolExecutor(32).map(one, ks))
c=collections.Counter((code, 'fresh' if age<25 else 'stale') for code,age in res)
print(sorted(c.items()))
PY
