#!/bin/bash
# reviewer job 5: (a) mechanism of the patch-1 regressions (mech.py, comb + strict) on 4 models; (b) dev3 vs comb on 4 more trigger models
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-volume-residue-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review
cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue-review/mech.py pkg/mech.py
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue-review/targets.json pkg/targets.json
PY=/opt/conv/env/bin/python
$PY - <<'PYEOF'
import json
pool=json.load(open('pkg/pool.json'))
want={'cc2895696435834b':'E-partial','c8f3e1a6c10b3496':'E-partial','5502b35f4feac183':'E-clean','40e1f70c0b271232':'E-clean'}
ms=[dict(id=o['id'],input_key=o['input_key'],size=o['size'],tag=want[o['id'][:16]]) for o in pool if o['id'][:16] in want]
json.dump(ms,open('pkg/models_E.json','w'),indent=0); print(len(ms))
PYEOF
mkdir -p mech
for i in 7ec85dca81b918c9 1ea774eb6201c3e1 df6df9298ccdbed4 e1828d1ce27d5aca; do
  for v in comb strict; do
    (OMP_NUM_THREADS=1 timeout 3000 $PY pkg/mech.py pkg/conv_$v/ifc2step6.py in/$i.bin pkg/targets.json $i mech/${v}_$i.json > mech/${v}_$i.log 2>&1; aws s3 cp --quiet mech/${v}_$i.json $R/mech/${v}_$i.json; aws s3 cp --quiet mech/${v}_$i.log $R/mech/${v}_$i.log) &
  done
done
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py E_dev3 $W/pkg/conv_dev3 $W/pkg/kit2 pkg/models_E.json --jobs 2 > E_dev3.log 2>&1; aws s3 cp --quiet E_dev3.log $R/E_dev3.log) &
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py E_comb $W/pkg/conv_comb $W/pkg/kit2 pkg/models_E.json --jobs 2 > E_comb.log 2>&1; aws s3 cp --quiet E_comb.log $R/E_comb.log) &
wait
echo ALL5 DONE > done5.txt; aws s3 cp --quiet done5.txt $R/done5.txt
