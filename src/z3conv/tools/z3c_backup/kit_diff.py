#!/usr/bin/env python3
"""read-only: compare local z3conv kit files with the deployed control copies (MD5 vs single-part ETag) - what a deploy would change"""
import boto3, hashlib, os, sys
s3 = boto3.Session(profile_name='annotationprod-publish').client('s3', region_name='ap-south-1')
CB = 'annotationprod'; CTL = 'cad-disk-extract/_control/z3conv'
Z = '/Users/dhiren/Downloads/Deccan/z3conv'
# files deploy.sh copies in from common/ before the upload (the local pipe dir may hold stale copies until then)
COMMON = {'ifc': ['convfleet.py', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'ifc_attrib.py'],
          'db1': ['convfleet.py', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'ifc_attrib.py'],
          'grade': ['convfleet.py', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'ifc_attrib.py'],
          'final': ['convfleet.py', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'ifc_attrib.py'],
          'sds2': ['convfleet.py'], 'verify': ['convfleet.py', 'ifc_attrib.py'], 'coord': ['grade_join.py']}
for pipe in sys.argv[1:]:
    remote = {}
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=CB, Prefix=f'{CTL}/{pipe}/'):
        for o in pg.get('Contents', []):
            n = o['Key'][len(f'{CTL}/{pipe}/'):]
            if '/' not in n:
                remote[n] = o['ETag'].strip('"')
    d = os.path.join(Z, pipe); diff = []
    for n in sorted(os.listdir(d)):
        if not n.endswith(('.py', '.sh', '.json', '.zip', '.txt')) or n in ('run.sh', 'userdata.sh'):
            continue
        p = os.path.join(Z, 'common', n) if n in COMMON.get(pipe, []) else os.path.join(d, n)
        md5 = hashlib.md5(open(p, 'rb').read()).hexdigest()
        r = remote.get(n)
        if r is None:
            diff.append(f'NEW {n}')
        elif '-' in r:
            diff.append(f'?multipart {n}')
        elif r != md5:
            diff.append(f'CHANGED {n}')
    print(pipe, diff or 'no differences')
