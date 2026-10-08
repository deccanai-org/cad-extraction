import boto3,json,collections,concurrent.futures as cf
s=boto3.Session(profile_name=None if (__import__('os').environ.get('AWS_ACCESS_KEY_ID') or __import__('os').environ.get('AWS_PROFILE')) else 'annotationprod-publish').client('s3',region_name='ap-south-1')
B='annotationprod';ST='cad-disk-extract/_state/db1-v2/'
keys=[o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B,Prefix=ST+'results/') for o in p.get('Contents',[])]
with cf.ThreadPoolExecutor(48) as ex: R=list(ex.map(lambda k: json.loads(s.get_object(Bucket=B,Key=k)['Body'].read()),keys))
json.dump(R,open('db1_results.json','w'),default=str)
print('DB1 results',len(R),dict(collections.Counter(r['status'] for r in R)))
by=collections.defaultdict(collections.Counter)
for r in R: by[r['engine']][r['status']]+=1
for e,c in sorted(by.items()): print('  ',e,dict(c))
ok=[r for r in R if r['status']=='ok']
w=sum(r['convert'].get('written',0) for r in ok); m=sum(r['convert'].get('members',0) for r in ok)
print('in ok files: members',m,'written',w, 'skipped', dict(sum((collections.Counter(r['convert'].get('skipped',{})) for r in ok), collections.Counter())))
print('readback', collections.Counter((r.get('readback') or {}).get('read_status','skipped' if 'skipped' in (r.get('readback') or {}) else 'n/a') for r in ok))
