#!/usr/bin/env python3
"""v5.x manifests (fleet outputs in conversions/sds2-step/<id>/v5.x/ and this agent's conversions): skipped pieces by
reason, and for 'absurd_extent_corrupt_source_geometry' the piece names (to compare with v4c, which wrote them)"""
import json, os, collections, boto3, re
from concurrent.futures import ThreadPoolExecutor
B = 'bim-proprietary-data'; W = '/work/agentwork/sds2-recall-nc1'
RES = 'cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-recall-nc1'
s3 = boto3.client('s3', region_name='ap-south-1')
st = json.load(open(os.path.join(W, 'inv', 'steps.json')))
ag = json.load(open(os.path.join(W, 'inv', 'agent_steps.json'))) if os.path.exists(os.path.join(W, 'inv', 'agent_steps.json')) else {}
todo = []
for jid, d in st.items():
    for lab, e in d.items():
        if lab.startswith('v5') and e.get('manifest'):
            todo.append((jid, lab, e['manifest'], 'fleet'))
for jid, d in ag.items():
    for lab, e in d.items():
        if e.get('manifest'):
            todo.append((jid, lab, e['manifest'], 'agent'))
def get(t):
    try:
        return t, json.loads(s3.get_object(Bucket=B, Key=t[2])['Body'].read())
    except Exception as ex:
        return t, None
reason = collections.Counter(); jobs_r = collections.Counter(); names = collections.Counter(); per_job = []
with ThreadPoolExecutor(32) as ex:
    for (jid, lab, key, src), m in ex.map(get, todo):
        if not m:
            continue
        sk = m.get('skipped') or {}
        br = sk.get('by_reason') or {}
        for r, n in br.items():
            reason[r] += n; jobs_r[r] += 1
        ab = [p for p in (sk.get('parts') or []) if 'absurd' in json.dumps(p)]
        for p in ab:
            names[(p.get('name') if isinstance(p, dict) else str(p))[:30]] += 1
        if br.get('absurd_extent_corrupt_source_geometry'):
            per_job.append([jid, lab, src, m.get('job'), m.get('version'), br.get('absurd_extent_corrupt_source_geometry'), (m.get('counts') or {}).get('placed_pieces')])
out = {'manifests': len(todo), 'skipped_by_reason_pieces': dict(reason), 'skipped_by_reason_jobs': dict(jobs_r),
       'absurd_extent_names_top': names.most_common(30), 'absurd_extent_jobs': sorted(per_job, key=lambda r: -r[5])}
json.dump(out, open(os.path.join(W, 'out', 'v5_skipped_scan.json'), 'w'), indent=1)
s3.upload_file(os.path.join(W, 'out', 'v5_skipped_scan.json'), B, f'{RES}/out/v5_skipped_scan.json')
print(json.dumps({k: out[k] for k in ('manifests', 'skipped_by_reason_pieces', 'skipped_by_reason_jobs', 'absurd_extent_names_top')}, indent=0)[:3000])
for r in out['absurd_extent_jobs'][:40]: print(r)
