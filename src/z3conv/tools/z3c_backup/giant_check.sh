#!/bin/bash
# READ-ONLY: giant host state - running jobs with a reservation >= 150 GB on any host, the giant host's load / memory / jobs per pipeline
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, time, collections
import boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
roots = {'d3': 'cad-disk-extract/zenitude-data-3/_state/conv', 'd4': 'cad-disk-extract/zentitude-data-4/_state/conv2'}
GH = 'ip-172-31-14-199.ap-south-2.compute.internal'; now = time.time()
big = []; gh = collections.Counter(); ghg = []
for tag, st in roots.items():
    for p in ('ifc', 'db1', 'sds2', 'grade', 'verify', 'package'):
        for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{st}/{p}/hosts/'):
            for o in pg.get('Contents', []):
                if now - o['LastModified'].timestamp() > 180: continue
                d = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read())
                for r in d.get('running') or []:
                    if (r.get('need') or 0) >= 150 << 30:
                        big.append((d['host'][:24], tag, p, r.get('id', '')[:16], r.get('since'), round((r.get('need') or 0) / 2**30), round((r.get('rss') or 0) / 2**30, 1)))
                if d['host'] == GH:
                    gh[f'{tag}:{p}'] += len(d.get('running') or [])
                    if p == 'sds2' and tag == 'd3':
                        print('  GH sds2 pid', d.get('pid'), 'running', [(r.get('id', '')[:12], round((r.get('need') or 0) / 2**30)) for r in d.get('running') or []], 'gate', {k: (d.get('gate') or {}).get(k) for k in ('exp_gb', 'need_gb', 'ok_mem', 'avail_gb', 'host_resv_gb', 'growth_gb')})
                    g = d.get('gate') or {}
                    ghg.append((tag, p, d.get('load'), d.get('mem_avail_gb'), g.get('exp_gb'), g.get('ok_mem'), g.get('ok_cpu'), g.get('prio_reserved_gb'), g.get('d3_reserved_gb')))
print('running jobs reserving >= 150 GB (count):', len(big))
for b in big: print('  BIG', b)
print('giant host jobs:', dict(gh))
for x in ghg: print('  gate', x)
PYEOF
