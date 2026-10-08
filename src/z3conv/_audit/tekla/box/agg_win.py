#!/usr/bin/env python3
"""Tekla audit (read-only): Windows (C#) pipeline results under derived/db1-step/**/result.json -> per engine manifest totals,
plus overlap with db1-v2 results (same sha) to find models whose ONLY DB1 STEP is a Windows output."""
import json, gzip, collections, time
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}, max_pool_connections=40))
B = 'bim-proprietary-data'; OUTP = 'cad-disk-extract/zenitude-data-3/_state/agentwork/tekla-audit'
def lst(prefix, suffix):
    out = []
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        out += [o['Key'] for o in p.get('Contents', []) if o['Key'].endswith(suffix)]
    return out
def getj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception as e: return {'_err': str(e)[:100]}
def i(x):
    try: return int(float(x or 0))
    except Exception: return 0
t0 = time.time()
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{OUTP}/rows.jsonl.gz')['Body'].read()).decode().splitlines()]
v2 = {r['id']: r for r in rows if r['ds'] == 'd12'}
keys = lst('cad-disk-extract/derived/db1-step/', 'result.json')
with ThreadPoolExecutor(16) as ex:
    docs = list(ex.map(getj, keys))
S = collections.defaultdict(lambda: {'n': 0, 'status': collections.Counter(), 'qa': collections.Counter(), 'tot': collections.Counter(),
                                     'v2_ok_same_sha': 0, 'v2_fail_same_sha': collections.Counter(), 'no_v2': 0, 'win_only_ok': 0,
                                     'win_only_ok_parts': 0, 'win_only_ok_failed': 0, 'fail_rate_hist': collections.Counter(), 'errors': collections.Counter()})
wrows = []
for k, d in zip(keys, docs):
    m = d.get('pipeline_manifest') or {}
    sha = d.get('db1_sha256') or (k.split('/by-sha256/')[1].split('/')[0] if '/by-sha256/' in k else k)
    eng = (m.get('engine') or '').replace('Xsteel', '').replace('Tekla Structures', '').strip() or ('v2:' + str((v2.get(sha) or {}).get('engine')))
    s = S[eng]; s['n'] += 1; st = d.get('status'); s['status'][str(st)] += 1; s['qa'][str(d.get('qa_verdict'))] += 1
    if st == 'OK':
        for f in ('parts', 'straight', 'curved', 'plates', 'polybeams', 'bolt_groups', 'bolts', 'failed_solids', 'solids_written', 'cuts_linked', 'cuts_applied', 'cuts_rejected'):
            s['tot'][f] += i(m.get(f))
        p = i(m.get('parts')); fsol = i(m.get('failed_solids'))
        if p: s['fail_rate_hist'][min(10, int(10 * fsol / p))] += 1
    else:
        s['errors'][str(m.get('error') or d.get('error') or st)[:60]] += 1
    r2 = v2.get(sha)
    if r2 is None: s['no_v2'] += 1
    elif r2.get('status') == 'ok': s['v2_ok_same_sha'] += 1
    else: s['v2_fail_same_sha'][str(r2.get('status'))] += 1
    if st == 'OK' and (r2 is None or r2.get('status') != 'ok'):
        s['win_only_ok'] += 1; s['win_only_ok_parts'] += i(m.get('parts')); s['win_only_ok_failed'] += i(m.get('failed_solids'))
    wrows.append({'id': sha, 'key': k, 'status': st, 'engine': eng, 'parts': i(m.get('parts')), 'straight': i(m.get('straight')), 'plates': i(m.get('plates')),
                  'bolts': i(m.get('bolts')), 'failed_solids': i(m.get('failed_solids')), 'solids_written': i(m.get('solids_written')),
                  'cuts_linked': i(m.get('cuts_linked')), 'cuts_applied': i(m.get('cuts_applied')), 'v2': (r2 or {}).get('status')})
out = {e: {kk: (dict(vv) if isinstance(vv, collections.Counter) else vv) for kk, vv in s.items()} for e, s in S.items()}
s3.put_object(Bucket=B, Key=f'{OUTP}/windows_summary.json', Body=json.dumps({'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'n': len(keys), 'by_engine': out}, indent=1).encode())
s3.put_object(Bucket=B, Key=f'{OUTP}/windows_rows.jsonl.gz', Body=gzip.compress('\n'.join(json.dumps(r) for r in wrows).encode()))
print('done', len(keys), round(time.time() - t0), flush=True)
