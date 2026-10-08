#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
PY=/opt/conv/env/bin/python
mkdir -p kit src data
aws s3 sync --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit/ --exclude hold --exclude canary.json --exclude env.json
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/db1/jobs.json data/jobs.json
$PY - <<'P'
import json, collections
J = json.load(open('data/jobs.json'))
print('jobs', len(J), 'total GB', round(sum(j.get('size') or 0 for j in J) / 1e9, 2))
print('keys', sorted(J[0].keys()))
for j in J:
    if j['id'][:4] in ('0762', '1d89', '4518', 'a944'):
        print(j['id'][:16], j.get('size'), j['input_key'][-90:])
P
$PY tools/fetch_src.py data/jobs.json src 0762effe 1d8972fb 4518a79a a9444257
ls -la src kit | head -50
