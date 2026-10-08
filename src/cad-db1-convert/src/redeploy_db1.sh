#!/bin/bash
# deploy current src to S3, purge all DB1 results/outputs, restart all 9 DB1 workers, drop pre-restart results
set -e
cd /Users/dhiren/Downloads/Deccan/cad-db1-convert && source .awsenv
for f in db1dec.py db1step.py db1old.py convert_one.py db1_worker.py; do aws s3 cp --only-show-errors src/$f s3://annotationprod/cad-disk-extract/_control/db1-v2/src/$f; done
aws s3 cp --only-show-errors layouts.json s3://annotationprod/cad-disk-extract/_control/db1-v2/layouts.json
venv/bin/python - <<'PY'
import boto3
s=boto3.Session().client('s3',region_name='ap-south-1'); B='annotationprod'
for pre in ('cad-disk-extract/_state/db1-v2/results/','cad-disk-extract/_state/db1-v2/claims/','cad-disk-extract/_state/db1-v2/deferred/','cad-disk-extract/conversions/db1-step/'):
    keys=[o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B,Prefix=pre) for o in p.get('Contents',[])]
    for i in range(0,len(keys),1000): s.delete_objects(Bucket=B,Delete={'Objects':[{'Key':k} for k in keys[i:i+1000]]})
    print('purged',pre.split('/')[-2],len(keys))
PY
date -u +%Y-%m-%dT%H:%M:%SZ > .restart_ts
HYD=i-02c28798f596f15ea,i-03cd15357838614be,i-05f15bbd50e3e5979,i-0862b1139c3b8783f
MUM=$(aws ec2 describe-instances --region ap-south-1 --filters "Name=tag:Name,Values=cad-db1-step-mum" "Name=instance-state-name,Values=running" --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' ',')
venv/bin/python src/ssm.py ap-south-2 $HYD src/restart_db1.sh 90 2>&1 | grep -c restarted || true
venv/bin/python src/ssm.py ap-south-1 $MUM src/restart_db1.sh 90 2>&1 | grep -c restarted || true
venv/bin/python src/ssm.py ap-south-1 i-0d44873a4951075f7 src/restart_db1_re.sh 200 2>&1 | grep -c "host=" || true
sleep 45
venv/bin/python - <<'PY'
import boto3, json, concurrent.futures as cf
TS=open('.restart_ts').read().strip()
s=boto3.Session().client('s3',region_name='ap-south-1'); B='annotationprod'; ST='cad-disk-extract/_state/db1-v2/results/'
keys=[o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B,Prefix=ST) for o in p.get('Contents',[])]
def chk(k):
    r=json.loads(s.get_object(Bucket=B,Key=k)['Body'].read())
    if r.get('started','') < TS:
        for kk in (k, f"cad-disk-extract/conversions/db1-step/{r['sha']}.stp", f"cad-disk-extract/_state/db1-v2/claims/{r['sha']}.json"): s.delete_object(Bucket=B,Key=kk)
        return 1
    return 0
with cf.ThreadPoolExecutor(32) as ex: n=sum(ex.map(chk,keys))
print('restart',TS,'dropped pre-restart results',n)
PY
