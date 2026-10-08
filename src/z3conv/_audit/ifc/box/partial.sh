#!/bin/bash
cd /work/agentwork/audit-ifc
/opt/conv/env/bin/python - <<'PY'
import os, gzip
W='/work/agentwork/audit-ifc'
with gzip.open(W+'/scan_partial.jsonl.gz','wt') as f:
    n=0
    for x in sorted(os.listdir(W+'/out')):
        if x.endswith('.json'):
            f.write(open(W+'/out/'+x).read().strip()+'\n'); n+=1
print(n)
PY
aws s3 cp --quiet scan_partial.jsonl.gz s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc/scan_partial.jsonl.gz
