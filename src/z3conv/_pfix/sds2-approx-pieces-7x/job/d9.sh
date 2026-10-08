#!/bin/bash
# d9: diag of cand8 (v5.5.3 + approx-pieces patch: repair stage incl. bridge-aware loops with cross-loop cancellation,
# negative-weight validation, section-area identity) on every fetched job + the SDS2 fixer's draft jobs (read-only)
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d9.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
pkill -f "diag.py.d8" ; pkill -f "diag_all_d8.sh"; pkill -f "$W/d8.sh"
bash $W/mkvar553.sh cand8 cand8_brep.py:brep.py cand8_to_step2.py:to_step2.py
bash $W/mkvar553.sh base553
cp $W/diag2.py $W/diag.py.d9
sed -e "s#\$W/diag.py#\$W/diag.py.d9#" $W/diag_all.sh > $W/diag_all_d9.sh
cat dirs_d7.txt dirs_fixer.txt > dirs_d9.txt
VARIANTS="cand8" DIRS=dirs_d9.txt NP=${NP:-10} bash $W/diag_all_d9.sh d9
VARIANTS="base553" DIRS=dirs_fixer.txt NP=7 bash $W/diag_all_d9.sh d9b
aws s3 cp --quiet $W/d9.log $R/d9.log
