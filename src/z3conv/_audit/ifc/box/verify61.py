#!/usr/bin/env python3
"""IFC audit: check that STEPs written by the deployed ifc2step6 6.1.0-rc carry the openings (kernel volumes with/without
openings vs the new STEP part volumes). Read-only; output verify61.jsonl.gz in the audit prefix."""
import os, sys, json, gzip, shutil
sys.path.insert(0, '/work/agentwork/audit-ifc')
import scan as S
NW = '/work/agentwork/audit-ifc/v61'
os.makedirs(NW + '/out', exist_ok=True); os.makedirs(NW + '/src', exist_ok=True)
shutil.copy('/work/agentwork/audit-ifc/graph.py', NW + '/graph.py')
S.W = NW
cont = {json.loads(l)['id']: json.loads(l) for l in gzip.open('/work/agentwork/audit-ifc/contents_ifc.jsonl.gz', 'rt')}
todo = json.loads(sys.argv[1])          # {id: out_key}
S.NVOL = 12
for mid, ok in todo.items():
    print(S.process((cont[mid], {'step_key': ok, 'reused': False, 'class': None})), flush=True)
with gzip.open(NW + '/verify61.jsonl.gz', 'wt') as f:
    for x in os.listdir(NW + '/out'):
        f.write(open(NW + '/out/' + x).read().strip() + '\n')
S.s3c().upload_file(NW + '/verify61.jsonl.gz', S.B, S.OUTK + '/verify61.jsonl.gz')
print('done')
