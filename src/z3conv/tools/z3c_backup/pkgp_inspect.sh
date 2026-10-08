#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import json, boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/dataset/packages/3d_partial/'
pids = [c['Prefix'][len(P):-1] for c in s3.list_objects_v2(Bucket=B, Prefix=P, Delimiter='/').get('CommonPrefixes') or []]
print('partial packages', len(pids))
for pid in pids:
    pj = json.loads(s3.get_object(Bucket=B, Key=f'{P}{pid}/project.json')['Body'].read())
    man = [json.loads(l) for l in s3.get_object(Bucket=B, Key=f'{P}{pid}/manifest.jsonl')['Body'].read().decode().split('\n') if l.strip()]
    print('==', pid[:90]); print(' tier', pj.get('tier'), 'addon_of', pj.get('addon_of'), 'sources', pj.get('sources'), 'partial_steps', pj.get('partial_steps'), 'files', pj.get('files'), 'GB', round(pj.get('bytes', 0)/1e9, 3), 'slots', pj.get('slots'))
    for r in man:
        if r.get('modality') == 'step':
            p = r.get('partial') or {}
            print(' STEP', r['relpath'][:70], 'class', r.get('class'), 'kind', p.get('kind'), 'issues', (p.get('issues') or [])[:3], 'converted_from', r.get('converted_from'), 'pkg', r.get('converted_from_package'))
            break
    print(' channels', sorted({r['relpath'].rsplit('/', 1)[0] for r in man}))
PY
