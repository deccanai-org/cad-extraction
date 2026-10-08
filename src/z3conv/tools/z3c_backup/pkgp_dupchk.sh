#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import json, boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; D = 'cad-disk-extract/dataset/packages/'
pid = 'Zenitude-data-3__Jobs & Data_Files_Completed_On_Server12_Data Files_10.10.40.50_7.331_DataFiles_Jobs'
full = [c['Prefix'][len(D + '3d_partial/'):-1] for c in s3.list_objects_v2(Bucket=B, Prefix=D + '3d_partial/' + pid, Delimiter='/').get('CommonPrefixes') or []]
pid = full[0]
def man(t): return [json.loads(l) for l in s3.get_object(Bucket=B, Key=f'{D}{t}/{pid}/manifest.jsonl')['Body'].read().decode().split('\n') if l.strip()]
pa, pe = man('3d_partial'), man('3d')
she = {r.get('sha256') for r in pe}
print('partial rows', len(pa), 'perfect rows', len(pe))
for r in pa: print(' ', r['relpath'][:60], r.get('modality'), 'class', r.get('class'), 'dup_of_perfect' if r.get('sha256') in she else 'unique', r.get('members_missing_count'))
PY
