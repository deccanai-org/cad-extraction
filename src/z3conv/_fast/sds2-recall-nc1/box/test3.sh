#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/sds2_ifc_recall.py .
cd $W/test
timeout 110 /opt/conv/env/bin/python - <<'PY'
import sys, json, collections
sys.path.insert(0, '/work/agentwork/sds2-recall-nc1')
import sds2_ifc_recall as R, ifc_products
F = ifc_products.load('/work/agentwork/sds2-recall-nc1/cache/ifc_a70140e95381c7cf.npz')
print(collections.Counter(R.ifc_role(r) for r in F['rows']).most_common(12))
print(collections.Counter(R.ifc_section(r) for r in F['rows'] if r[1]=='IfcBuildingElementProxy').most_common(5))
print([r[:6] for r in F['rows'] if r[1]=='IfcBuildingElementProxy'][:3])
res = R.run('t1.step', '/work/agentwork/sds2-recall-nc1/cache/ifc_a70140e95381c7cf.npz', 25.0, 'v5.1', 'sheel', index_cache='t1.pkl')
print(json.dumps({k: res.get(k) for k in ('status','registration','overall','recall_by_ifc_role','precision_by_step_kind','section_agreement_on_matched','plan_overlap')}, default=str)[:3000])
PY
