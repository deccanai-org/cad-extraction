import boto3, json, sys, time
s3 = boto3.Session(profile_name='annotationprod-publish').client('s3', region_name='ap-south-1')
B = 'annotationprod'; ST = 'cad-disk-extract/zenitude-data-2/_state/s3d3d/'
jobs = json.loads(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-2/_control/s3d3d/jobs.json')['Body'].read())
ids = {j['id'] for j in jobs if j['kind'] != 'area_png'}
while True:
    have = set()
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=ST + 'results/'):
        have |= {o['Key'].rsplit('/', 1)[-1][:-5] for o in p.get('Contents', [])}
    miss = sorted(ids - have)
    print(time.strftime('%H:%M:%S'), 'missing', len(miss), miss[:8], flush=True)
    if not miss or len(sys.argv) < 2:
        break
    time.sleep(60)
