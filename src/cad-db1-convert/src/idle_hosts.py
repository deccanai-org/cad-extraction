"""Mumbai conversion hosts (r7i, cad-db1-step-mum) with 0 running jobs in the last two heartbeats"""
import boto3, json, datetime as dt, time
s=boto3.Session().client('s3',region_name='ap-south-1'); B='annotationprod'; P='cad-disk-extract/_state/db1-v2/hosts/'
now=dt.datetime.now(dt.timezone.utc)
for o in s.list_objects_v2(Bucket=B,Prefix=P).get('Contents',[]):
    if not o['Key'].endswith('.json') or 'fatal' in o['Key'] or (now-o['LastModified']).total_seconds()>300: continue
    h=json.loads(s.get_object(Bucket=B,Key=o['Key'])['Body'].read())
    if h['host'].startswith('ip-10-0-102-') and h.get('mem_total_gb',0) > 400:
        print(h['host'], h.get('code'), len(h.get('running',[])))
