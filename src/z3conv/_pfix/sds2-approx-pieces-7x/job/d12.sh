#!/bin/bash
# d12: cand9 (final: + tube identity) diag on the jobs where cand8 still rejected closed B-reps on weight / size
W=/work/agentwork/sds2-approx-pieces-7x
exec > $W/d12.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
while [ ! -f $W/diag/d11/DONE ]; do sleep 30; done
VARIANTS="cand9" DIRS=dirs_d12.txt NP=${NP:-5} bash $W/diag_all_d9.sh d12
