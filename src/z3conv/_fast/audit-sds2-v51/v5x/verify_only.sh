#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x-verify; mkdir -p $D && cd $D
F=s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/fixes/audit-sds2-v5x
aws s3 cp --quiet $F/repair_state.py . && aws s3 cp --quiet $F/repair_plan.json .
timeout 100 /opt/conv/env/bin/python repair_state.py --plan repair_plan.json --only prefer,restore 2>&1 | python3 -c "
import sys, json
t = sys.stdin.read(); i = t.rindex('\n{'); log = json.loads(t[:i]); print(t[i:].strip())
for x in log: print(x['id'][:12], x['action'], (x.get('grade_before') or {}).get('class'), '->', (x.get('grade_after') or {}).get('class'), x.get('skip') or '', x.get('error') or '')"
cd / && rm -rf $D && echo cleaned
