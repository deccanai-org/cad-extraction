#!/usr/bin/env python3
"""per-box table from live worker heartbeats (bim read-only): load / vCPU, jobs per pipeline, memory, worker generations, claim gate"""
import boto3, json, time, collections, sys
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
t = time.time(); objs = []
for p in ('ifc', 'db1', 'sds2', 'grade', 'final', 'verify', 'package'):
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{ST}/{p}/hosts/'):
        objs += [(p, o) for o in pg.get('Contents', []) if t - o['LastModified'].timestamp() < 180]
def gj(x):
    try: return x[0], json.loads(s3.get_object(Bucket=B, Key=x[1]['Key'])['Body'].read())
    except Exception: return x[0], None
with ThreadPoolExecutor(64) as ex:
    hb = [x for x in ex.map(gj, objs) if x[1]]
H = collections.defaultdict(list)
for p, h in hb: H[h['host']].append((p, h))
rows = []
for host, L in H.items():
    newest = max((h for _, h in L), key=lambda h: h.get('at') or '')
    prim = next((h.get('primary_pipe') for _, h in L if h.get('primary_pipe')), '?')
    jobs = collections.Counter(); v = collections.Counter(); rss = 0; need = 0
    for p, h in L:
        jobs[p] += len(h.get('running') or []); v[h.get('runtime', '')[-2:]] += 1
        rss += sum((r.get('rss') or 0) for r in h.get('running') or []); need += sum((r.get('need') or 0) for r in h.get('running') or [])
    g = max((h.get('gate') or {} for _, h in L), key=lambda g: g.get('at') or '')
    rows.append((prim or '?', host[:22], newest.get('cpus'), round(newest.get('load') or 0), dict(jobs), newest.get('mem_avail_gb'), newest.get('mem_total_gb'),
                 round(rss / 2**30), round(need / 2**30), dict(v), g.get('ok_cpu'), g.get('ok_mem'), g.get('host_resv_gb')))
rows.sort()
print(f"{'pipe':6} {'host':22} {'cpu':>3} {'load':>4} {'avail/tot GB':>12} {'rss':>4} {'resv':>4}  jobs | procs(v1/v2) | gate cpu/mem")
for r in rows:
    print(f"{r[0]:6} {r[1]:22} {r[2]:>3} {r[3]:>4} {str(r[5])+'/'+str(r[6]):>12} {r[7]:>4} {r[8]:>4}  {r[4]} | {r[9]} | {r[10]}/{r[11]} resv={r[12]}")
print('boxes', len(rows), 'vcpu', sum(r[2] or 0 for r in rows), 'load', sum(r[3] for r in rows))
