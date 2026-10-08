#!/bin/bash
cd /work/agentwork/audit-ifc
for f in graph2.py class1check.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/$f $f; done
taskset -c 46-63 /opt/conv/env/bin/python - <<'PY'
import json, gzip, os, sys
sys.path.insert(0, '/work/agentwork/audit-ifc')
import class1check as K
cont = {json.loads(l)['id']: json.loads(l) for l in gzip.open('contents_ifc.jsonl.gz', 'rt')}
info = json.load(open('model_info.json'))
# pick 3 class-1 models: one reused SDS/2, one with voids if any, one s6
ids = [m for m, i in info.items() if i.get('class') == 1][:3]
for m in ids:
    print(K.one((cont[m], info[m])))
    d = json.load(open(os.path.join(K.OUTD, m + '.json')))
    g = d.get('g2') or {}
    print(m[:16], {k: g.get(k) for k in ('products_with_body', 'multi_body', 'multi_body_ids', 'brep_voids', 'sec')}, d.get('errs'), d.get('error'))
PY
