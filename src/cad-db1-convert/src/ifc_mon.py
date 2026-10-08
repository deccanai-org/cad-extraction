import boto3,json,collections,concurrent.futures as cf,datetime
s=boto3.Session(profile_name=None if (__import__('os').environ.get('AWS_ACCESS_KEY_ID') or __import__('os').environ.get('AWS_PROFILE')) else 'annotationprod-publish').client('s3',region_name='ap-south-1')
B='annotationprod';ST='cad-disk-extract/_state/ifc-step/'
keys=[o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B,Prefix=ST+'results/') for o in p.get('Contents',[])]
def g(k): return json.loads(s.get_object(Bucket=B,Key=k)['Body'].read())
with cf.ThreadPoolExecutor(64) as ex: R=list(ex.map(g,keys))
c=collections.Counter(r.get('status') for r in R)
dfr=[o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B,Prefix=ST+'deferred/') for o in p.get('Contents',[])]
done_ids={r['id'] for r in R}
print(f"results {len(R)}/9129 {dict(c)} in={sum(r['in_bytes'] for r in R)/1e9:.1f}GB of 289.5 out={sum(r.get('out_bytes',0) for r in R)/1e9:.1f}GB deferred_pending={sum(1 for k in dfr if k.split('/')[-1][:-5] not in done_ids)}")
now=datetime.datetime.utcnow()
for o in s.list_objects_v2(Bucket=B,Prefix=ST+'hosts/ip-')['Contents']:
    if o['Key'].endswith('fatal.json'): continue
    d=g(o['Key']); age=(now-datetime.datetime.strptime(d['at'],'%Y-%m-%dT%H:%M:%SZ')).total_seconds()/60
    if age<30: print(f"  {o['Key'].split('/')[-1][:20]} age={age:.0f}m run={len(d['running'])} avail={d['mem_avail_gb']} total={d['mem_total_gb']} {d['stats']}")
json.dump(R,open('ifc_results.json','w'))
