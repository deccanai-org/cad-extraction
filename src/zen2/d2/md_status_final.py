#!/usr/bin/env python3
"""aggregate all hosts' model_drawings results from S3 into the status part 'model_drawings'."""
import gzip, json, sys, collections
sys.path.insert(0, '/work/2d')
import md_run, status
res = {}
for page in md_run.s3().get_paginator('list_objects_v2').paginate(Bucket=md_run.BK, Prefix=md_run.P + '_state/d2_md_results/'):
    for o in page.get('Contents', []):
        for l in gzip.decompress(md_run.s3().get_object(Bucket=md_run.BK, Key=o['Key'])['Body'].read()).decode().splitlines():
            if l.strip():
                r = json.loads(l)
                res[r['key']] = r
idx = md_run.load_index()
totals = dict(collections.Counter((r.get('file_type') or '').lower() for r in idx))
s = md_run.summarize(res, totals)
import re
kinds = collections.defaultdict(collections.Counter)
for r in res.values():
    if r.get('type') != 'sha':
        continue
    fn = (r.get('file_name') or '')
    k = 'ISO (isometric sheet)' if fn.upper().startswith('ISO') else (re.sub(r'^CopyOf', '', re.sub(r'[\d({].*', '', fn)) or 'other')[:20]
    kinds[k]['png' if r.get('png') else ('no geometry' if r.get('status') == 'ok' else r.get('status'))] += 1
s['sha']['by_kind'] = {k: dict(v) for k, v in sorted(kinds.items(), key=lambda x: -sum(x[1].values()))[:15]}
iso = [r for r in res.values() if r.get('type') == 'sha' and (r.get('file_name') or '').upper().startswith('ISO') and r.get('png')]
if iso:
    e = sorted(r.get('dxf_entities', 0) for r in iso)
    s['sha']['iso_entities_p10_p50_p90'] = [e[len(e) // 10], e[len(e) // 2], e[9 * len(e) // 10]]
s['stage'] = 'done'
s['model_index'] = 's3://annotationprod/cad-disk-extract/zenitude-data-2/json/model_drawing_index.json'
status.put_part('model_drawings', s)
print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != 'failures'}) for k, v in s.items()})[:1500])
