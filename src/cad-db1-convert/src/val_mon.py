import boto3,json,collections,concurrent.futures as cf,sys
s=boto3.Session(profile_name=None if (__import__('os').environ.get('AWS_ACCESS_KEY_ID') or __import__('os').environ.get('AWS_PROFILE')) else 'annotationprod-publish').client('s3',region_name='ap-south-1')
B='annotationprod'; P='cad-disk-extract/_state/db1-v2/val/'
keys=[o['Key'] for p in s.get_paginator('list_objects_v2').paginate(Bucket=B,Prefix=P) for o in p.get('Contents',[])]
with cf.ThreadPoolExecutor(32) as ex: R=list(ex.map(lambda k: json.loads(s.get_object(Bucket=B,Key=k)['Body'].read()),keys))
json.dump(R,open('pairs/val_results.json','w'),indent=1,default=str)
R.sort(key=lambda r:(r.get('status',''),r.get('engine',''),r.get('tag','')))
for r in R:
    m=r.get('members') or 0; mt=r.get('match') or 0
    print(f"{r.get('status','')[:4]} {r['tag']:17} {r.get('mb','?'):>6}MB {r.get('secs','?'):>6}s mem={m:<6} ifc={r.get('ifc','-'):<6} match={mt:<6} prec={mt/m if m else 0:.2f} prof_ok={r.get('prof_ok',0):<6} y_ok={r.get('y_ok',0):<6} {str(r.get('err',''))[:50]}")
print(len(R),'results')
