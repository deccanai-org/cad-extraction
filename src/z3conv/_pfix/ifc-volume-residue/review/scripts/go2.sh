#!/bin/bash
# reviewer job 2: D (different models: patch triggers + class-1 controls) dev3 vs comb, and census v2/v3 on live STEP parts
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-volume-residue-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review
cd $W
PY=/opt/conv/env/bin/python
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py D_dev3 $W/pkg/conv_dev3 $W/pkg/kit2 pkg/models_D.json --jobs 1 > D_dev3.log 2>&1; aws s3 cp --quiet D_dev3.log $R/D_dev3.log) &
(V6_VERIFY_PROCS=2 $PY pkg/batch3.py D_comb $W/pkg/conv_comb $W/pkg/kit2 pkg/models_D.json --jobs 1 > D_comb.log 2>&1; aws s3 cp --quiet D_comb.log $R/D_comb.log) &
wait
echo ALL2 DONE > done2.txt; aws s3 cp --quiet done2.txt $R/done2.txt
