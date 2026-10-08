#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import boto3, json, collections
from concurrent.futures import ThreadPoolExecutor
s3=boto3.client('s3'); B='bim-proprietary-data'
pk=set(); 
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix='cad-disk-extract/dataset/packages/3d/', Delimiter='/'):
    pk |= {c['Prefix'].split('/')[-2] for c in pg.get('CommonPrefixes') or []}
print('package prefixes', len(pk))
for ST in ('cad-disk-extract/_state/packaging',):
    keys=[]
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=ST+'/ledger_parts/'):
        keys += [o['Key'] for o in pg.get('Contents') or []]
    def g(k):
        try: return k, json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
        except Exception as e: return k, None
    c=collections.Counter(); bad=[]; seen=set()
    with ThreadPoolExecutor(32) as ex:
        for k,d in ex.map(g, keys):
            if d is None: c['unreadable']+=1; continue
            if d.get('removed'): c['removed']+=1; continue
            pid=k.rsplit('/',1)[-1][:-5]
            v={'ok': d.get('verify_ok')} if 'verify_ok' in d else (d.get('verify') or {})
            st=(v.get('ok') if isinstance(v,dict) else v) if v else ('no_verify_field:'+','.join(sorted(d.keys()))[:120])
            c[('in_pkgs' if pid in pk else 'NOT_in_pkgs', str(st))]+=1
            seen.add(pid)
            if str(st) not in ('ok','verify_ok','True') and len(bad)<5: bad.append((k.rsplit('/',1)[-1][:80], str(v)[:200]))
    print(ST, len(keys), dict(c)); print('packages without ledger part', len(pk-seen), sorted(pk-seen)[:5])
PY
