#!/bin/bash
# d10b: fetch the 3 approx-only models missing from the cached jobs.json (files manifests) and diag them
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d10b.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
: > dirs_only2.txt
for id in 20e8849c 2f4e4896 91cf26ea; do
  timeout 900 $W/env/bin/python $W/getjob4.py $id $W/jobs >> dirs_only2.txt 2>> fetch_only2.err
done
cat dirs_only2.txt
VARIANTS="cand9 base553" DIRS=dirs_only2.txt NP=3 bash $W/diag_all_d9.sh d10b
VARIANTS="cand9" DIRS=dirs_only.txt NP=2 bash $W/diag_all_d9.sh d10c
