import json, random, boto3, collections, re
s=boto3.client('s3',region_name='ap-south-1'); B='annotationprod'; D='cad-disk-extract/dataset/main/'
J=json.loads(s.get_object(Bucket=B,Key='cad-disk-extract/_control/db1-v2/db1_jobs.json')['Body'].read())['jobs']
random.seed(7); smp=random.sample([j for j in J if j['engine']!='None'], 80)
res=collections.Counter(); ex=[]; cache={}
for j in smp:
    parts=j['key'].split('/'); pid=f"{parts[1]}__{parts[2]}"; found=None
    for route in ('3d','2d'):
        k=f"{D}{route}/{pid}/manifest.jsonl"
        if k not in cache:
            try: cache[k]=s.get_object(Bucket=B,Key=k)['Body'].read().decode()
            except Exception: cache[k]=''
        if j['key'] in cache[k]: found=route; break
        if cache[k] and not found: exists_proj=route
    if not found:
        anyp=[r for r in ('3d','2d') if cache.get(f"{D}{r}/{pid}/manifest.jsonl")]
        res['NOT_FOUND_project_'+('exists' if anyp else 'missing')]+=1
        if len(ex)<4: ex.append((pid[:60], j['key'][-70:], anyp))
    else: res['found_'+found]+=1
print(dict(res)); print(ex)
