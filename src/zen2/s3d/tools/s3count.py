import boto3, collections
s3 = boto3.Session(profile_name='annotationprod-publish').client('s3', region_name='ap-south-1')
pre = 'cad-disk-extract/zenitude-data-2/model/'
c = collections.Counter(); b = collections.Counter()
for p in s3.get_paginator('list_objects_v2').paginate(Bucket='annotationprod', Prefix=pre):
    for o in p.get('Contents', []):
        k = o['Key'][len(pre):]
        parts = k.split('/')
        top = parts[0] if parts[0] != 'json' else 'json/' + (parts[1] if len(parts) > 2 else parts[1])
        ext = k.rsplit('.', 1)[-1] if '.' in parts[-1] else ''
        if k.endswith('.stats.json') or k.endswith('.validate.json'): ext = k.rsplit('.', 2)[-2] + '.json'
        c[(top, ext)] += 1; b[(top, ext)] += o['Size']
for k in sorted(c):
    print('%-28s %-14s %8d files %10.2f GB' % (k[0], k[1], c[k], b[k] / 1e9))
