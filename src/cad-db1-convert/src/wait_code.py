import boto3, json, time, datetime as dt
s=boto3.Session().client('s3',region_name='ap-south-1'); B='annotationprod'; P='cad-disk-extract/_state/db1-v2/hosts/'
CODE='db1-2026-09-25b'
for it in range(60):
    live={}; now=dt.datetime.now(dt.timezone.utc)
    for o in s.list_objects_v2(Bucket=B,Prefix=P).get('Contents',[]):
        if not o['Key'].endswith('.json') or 'fatal' in o['Key']: continue
        if (now-o['LastModified']).total_seconds()>600: continue
        h=json.loads(s.get_object(Bucket=B,Key=o['Key'])['Body'].read()); live[h['host']]=(h.get('code'), len(h.get('running',[])), h.get('stats'))
    new=[k for k,v in live.items() if v[0]==CODE]
    print(time.strftime('%H:%M:%SZ',time.gmtime()), 'live', len(live), 'on new code', len(new), flush=True)
    if live and len(new)==len(live):
        for k,v in live.items(): print('  ',k[:36],v)
        break
    time.sleep(60)
