#!/bin/bash
# Memory profile of the SDS2 converter phases on big jobs (v5.4 code = v54g): conversion only, then verify only.
W=/work/agentwork/sds2v54
cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/prof
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/maxrss.py $W/maxrss.py
mkdir -p $W/prof
P=$W/v54g/sds2-step-pipeline/decode
for J in $W/jobs/MORROW_HS_JOB_ABM_BACKUP_022022_e56431 $W/jobs3/KJL_f3e696; do
  [ -d "$J" ] || continue
  N=$(basename $J); O=$W/prof/$N; mkdir -p $O
  $W/env/bin/python $W/maxrss.py "$N convert(no verify)" $W/prof/prof.jsonl $W/env/bin/python -u $P/sds2_to_step.py $J -o $O/${N}_stage2.step --stage 2 > $O/convert.log 2>&1
  ls -la $O/${N}_stage2.step >> $O/sizes.txt
  $W/env/bin/python $W/maxrss.py "$N verify(full, with preview)" $W/prof/prof.jsonl $W/env/bin/python -u $P/verify_step.py $O/${N}_stage2.step $O/${N}_preview.png > $O/verify.log 2>&1
  $W/env/bin/python $W/maxrss.py "$N verify(no preview)" $W/prof/prof.jsonl $W/env/bin/python -u $P/verify_step.py $O/${N}_stage2.step > $O/verify_np.log 2>&1
  aws s3 cp --quiet $W/prof/prof.jsonl $R/prof.jsonl
done
date -u +%FT%TZ > $W/PROF_DONE
aws s3 cp --quiet $W/PROF_DONE $R/PROF_DONE
