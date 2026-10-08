#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
for D in zenitude-data-3/_state/conv zentitude-data-4/_state/conv2; do
  for f in redo.json jobs_reconvert.json; do
    aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/$D/db1/$f /tmp/q.json 2>/dev/null && python3 -c "import json;d=json.load(open('/tmp/q.json'));d=d.get('ids',d.get('jobs',d)) if isinstance(d,dict) else d;print('$D $f',len(d))" || echo "$D $f none"
  done
  aws s3 ls s3://bim-proprietary-data/cad-disk-extract/$D/db1/redo.json
done
grep -h "db1" /opt/z3c/index.log | tail -2 | cut -c1-300; date -u
