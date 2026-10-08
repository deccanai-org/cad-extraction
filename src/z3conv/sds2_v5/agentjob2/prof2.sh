#!/bin/bash
# Peak RSS / wall of the full fleet command (sds2_to_step --stage 2 --verify): v5.4 (single process) vs v5.4.1 (forked phases)
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/prof
mkdir -p $W/prof2
for J in $W/jobs/MORROW_HS_JOB_ABM_BACKUP_022022_e56431 $W/jobs3/01-NOV-21_RH_PALO_ALTO_JOB_88fb6a; do
  [ -d "$J" ] || continue
  N=$(basename $J)
  for V in v54g v541; do
    O=$W/prof2/$V/$N; mkdir -p $O
    $W/env/bin/python $W/maxrss.py "$N $V full --verify" $W/prof2/prof2.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1 &
  done
  wait
  aws s3 cp --quiet $W/prof2/prof2.jsonl $R/prof2.jsonl
done
date -u +%FT%TZ > $W/PROF2_DONE
aws s3 cp --quiet $W/PROF2_DONE $R/PROF2_DONE
