#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PY'
import boto3, json, datetime
s3=boto3.client('s3'); B='bim-proprietary-data'
pid='Zenitude-data-3__Completed_Projects_Data_000_Technical Library7_Zip Jobs_MT19_087 (610 Walnut Street).7z'
k=f'cad-disk-extract/_state/packaging/verify_fail/{pid}.json'
d=json.loads(s3.get_object(Bucket=B,Key=k)['Body'].read())
if d.get('resolved'): print('RESULT already resolved'); raise SystemExit
d.update(resolved=True, resolved_at=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
         resolved_by='operator (owner-approved 2026-10-04 PDT): dedup removal run 4 removed the 76 dedup_non_primary STEP rows behind step_not_shipped; remaining step_key_changed is a normal refresh')
s3.put_object(Bucket=B,Key=k,Body=json.dumps(d,indent=1).encode(),ContentType='application/json')
print('RESULT resolved', d['attempts'], d['packager'])
PY
