#!/bin/bash
# d8: diag of cand7 (= cand6 + negative-weight validation + section-area identity) on every fetched job
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d8.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
bash $W/mkvar553.sh cand7 cand7_brep.py:brep.py cand7_to_step2.py:to_step2.py
cp $W/diag2.py $W/diag.py.d8
sed -e "s#\$W/diag.py#\$W/diag.py.d8#" $W/diag_all.sh > $W/diag_all_d8.sh
VARIANTS="cand7" DIRS=dirs_d7.txt NP=${NP:-6} bash $W/diag_all_d8.sh d8
aws s3 cp --quiet $W/d8.log $R/d8.log
