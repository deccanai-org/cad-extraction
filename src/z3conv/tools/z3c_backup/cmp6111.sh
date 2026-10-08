#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, collections
from concurrent.futures import ThreadPoolExecutor
s3=boto3.client('s3')
ids=json.loads(boto3.client('s3').get_object(Bucket='annotationprod',Key='cad-disk-extract/_control/z3conv/coord_tmp/c6111_ids.json')['Body'].read())
B='bim-proprietary-data'; D='cad-disk-extract/zenitude-data-3/_state/conv/ifc/detail/'
TAGS=('L1','L1-triangulated','L1-tessellated-analytic','L2','L2-alt-source','L3','L3-partial-surface','L4','L4-surface','open-surface','open_in_source','unverified')
def est(r):
    if not r or r.get('status')!='ok': return (1,0,0,0,0,0)
    v=r.get('validate') or {}; j=r.get('join') or {}; cov=(j.get('coverage') or {}).get('all')
    t=((r.get('step') or {}).get('v6') or {}).get('tags')
    fb=sum((n or 0) for k,n in t.items() if k in TAGS) if isinstance(t,dict) else 0
    return (0,-(cov if cov is not None else 0),(v.get('invalid_solids_est') or v.get('invalid') or 0)+(v.get('nonpos_vol') or 0),j.get('surface_parts') or 0,(j.get('volume') or {}).get('outside_5pct') or 0,fb)
def g(k):
    try: return json.loads(s3.get_object(Bucket=B,Key=k)['Body'].read())
    except Exception: return None
def one(i):
    return i, g(D+i+'.v6111-rc2.result.json'), g(D+i+'.v6110-ctl.result.json')
c=collections.Counter(); worse=[]; better=[]
with ThreadPoolExecutor(32) as tp:
    for i,rc,ctl in tp.map(one,ids):
        if rc is None or ctl is None: c['missing_'+('rc' if rc is None else 'ctl')]+=1; continue
        a,b=est(rc),est(ctl)
        if a==b: c['same']+=1
        elif a<b: c['rc_better']+=1; better.append((i[:16],b,a))
        else: c['rc_worse']+=1; worse.append((i[:16],b,a,rc.get('reason')))
        c['rc_ok' if rc.get('status')=='ok' else 'rc_fail']+=1; c['ctl_ok' if ctl.get('status')=='ok' else 'ctl_fail']+=1
print('RESULT',dict(c))
for w in worse: print('RESULT WORSE (ctl -> rc)',w)
for w in better[:40]: print('RESULT BETTER (ctl -> rc)',w)
PY
