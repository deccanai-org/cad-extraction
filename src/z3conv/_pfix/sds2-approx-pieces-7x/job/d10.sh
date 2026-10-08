#!/bin/bash
# d10: fetch the data-3 models whose only class-1 blocker is "sds2 approx pieces" and diag them (cand8 + base553)
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d10.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
: > dirs_only.txt
for id in 20e8849c 2f4e4896 4a955413 91cf26ea ade4790f; do
  timeout 900 $W/env/bin/python $W/getjob3.py $id $W/jobs >> dirs_only.txt 2>> fetch_only.err
done
cat dirs_only.txt; du -sh $(cat dirs_only.txt)
while [ ! -d $W/cand8/sds2-step-pipeline ] || [ ! -f $W/diag.py.d9 ]; do sleep 10; done
VARIANTS="cand8 base553" DIRS=dirs_only.txt NP=4 bash $W/diag_all_d9.sh d10
aws s3 cp --quiet $W/d10.log $R/d10.log
