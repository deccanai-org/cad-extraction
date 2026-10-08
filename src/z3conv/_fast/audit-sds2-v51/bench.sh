#!/bin/bash
# local before/after: same job, three converter builds, same CLI as the fleet; /usr/bin/time -l gives wall + max RSS
cd /Users/dhiren/Downloads/Deccan/z3conv/_fast/audit-sds2-v51
PY=/Users/dhiren/Downloads/Deccan/z3conv/sds2_v5/venv/bin/python
export MPLBACKEND=Agg PYTHONUNBUFFERED=1
for job in FS41 WLCSC Godzilla; do
  for v in v4 v5 v5.1; do
    o=bench/$job/$v; mkdir -p $o
    ( cd $o && /usr/bin/time -l $PY -u ../../../pipe/$v/sds2-step-pipeline/decode/sds2_to_step.py ../../../jobs/$job -o ${job}_stage2.step --stage 2 --verify > run.log 2> time.txt )
    echo "$job $v rc=$? $(grep -E 'real|maximum resident' $o/time.txt | tr '\n' ' ')" >> bench/summary.txt
  done
done
echo DONE >> bench/summary.txt
