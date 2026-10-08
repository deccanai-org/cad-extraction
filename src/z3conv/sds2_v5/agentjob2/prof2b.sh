#!/bin/bash
# MORROW v5.4.1 full command (--verify, read-back + repair) peak RSS, alone
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/prof
J=$W/jobs/MORROW_HS_JOB_ABM_BACKUP_022022_e56431; N=$(basename $J); O=$W/prof2b/v541/$N; rm -rf $O; mkdir -p $O
$W/env/bin/python $W/maxrss.py "$N v541 full --verify" $W/prof2b/prof2b.jsonl $W/env/bin/python -u $W/v541/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
aws s3 cp --quiet $W/prof2b/prof2b.jsonl $R/prof2b.jsonl
grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log; aws s3 cp --quiet $O/${N}_stage2.log $R/prof2b_morrow_stage2.log
date -u +%FT%TZ > $W/PROF2B_DONE; aws s3 cp --quiet $W/PROF2B_DONE $R/PROF2B_DONE
