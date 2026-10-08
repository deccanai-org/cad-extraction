#!/bin/bash
cd /work/agentwork/sds2-recall-nc1/test
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/_state/ec2-results/0074d6c95e30f95614571589d99484f0357231a85894b6a11e5a6c10e1dada1d.json e1.json
timeout 60 /opt/conv/env/bin/python - <<'PY'
import json
d = json.load(open('e1.json'))
print(list(d.keys()))
for k, v in d.items():
    if isinstance(v, list):
        print(k, 'list', len(v), json.dumps(v[:2])[:600])
    elif isinstance(v, dict):
        print(k, 'dict', len(v), json.dumps(dict(list(v.items())[:2]))[:600])
    else:
        print(k, repr(v)[:200])
PY
