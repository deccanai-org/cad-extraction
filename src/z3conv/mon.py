#!/usr/bin/env python3
"""quick monitor from the Mac (bim profile, read-only): boot files, live worker heartbeats, results by status/reason per pipeline"""
import boto3, json, time, collections, sys
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
pipes = sys.argv[1:] or ['ifc', 'db1', 'sds2', 'grade']
def lst(p):
    out = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=p):
        out += pg.get('Contents', [])
    return out
def gj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception: return None
t = time.time()
for p in pipes:
    boots = [o for o in lst(f'{ST}/{p}/boot/') if o['Key'].endswith('.txt')]
    hosts = [o for o in lst(f'{ST}/{p}/hosts/') if t - o['LastModified'].timestamp() < 300]
    res = [o for o in lst(f'{ST}/{p}/results/') if o['Key'].endswith('.json')]
    claims = [o for o in lst(f'{ST}/{p}/claims/') if t - o['LastModified'].timestamp() < 1500]
    retry = lst(f'{ST}/{p}/retry/')
    recent = sorted(res, key=lambda o: -o['LastModified'].timestamp())[:400]
    with ThreadPoolExecutor(32) as ex:
        rr = [r for r in ex.map(lambda o: gj(o['Key']), recent) if r]
    c = collections.Counter((r.get('status'), r.get('reason')) for r in rr)
    hs = [gj(o['Key']) for o in hosts]
    run = sum(len(h.get('running') or []) for h in hs if h)
    print(f'== {p}: boots {len(boots)}  live procs {len(hosts)}  running {run}  claims {len(claims)}  results {len(res)}  retry {len(retry)}')
    for k, n in c.most_common(12):
        print('   ', n, k)
    for h in hs[:20]:
        if h: print('    host', h['host'][:20], h['code'], 'slots', h['slots'], 'run', len(h.get('running') or []), 'mem', h['mem_avail_gb'], '/', h['mem_total_gb'], 'disk', h['disk_free_gb'], h['stats'])
