#!/bin/bash
# d11: base553 diag (the "before" of the per-version table) on the data-3 jobs, after d9 / d9b
W=/work/agentwork/sds2-approx-pieces-7x
exec > $W/d11.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
while [ ! -f $W/diag/d9b/DONE ]; do sleep 30; done
VARIANTS="base553" DIRS=dirs_d7.txt NP=${NP:-8} bash $W/diag_all_d9.sh d11
