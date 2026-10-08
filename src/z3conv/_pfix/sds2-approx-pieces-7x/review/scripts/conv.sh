#!/bin/bash
# conv.sh VARIANT JOBDIR -> stage 2 --verify; results (no STEP) to S3
V=$1; J=$2; N=$(basename "$J"); W=/work/agentwork/sds2-approx-pieces-7x-review; O=$W/out/$V/$N
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x-review
PY=/work/agentwork/sds2v54/env/bin/python
mkdir -p $O
while [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 120 ]; do sleep 30; done
export PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1 AWS_DEFAULT_REGION=ap-south-1
cd $O; t0=$(date +%s)
/usr/bin/time -v timeout 14400 $PY -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py "$J" -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2> $O/time.log
echo "rc=$? wall=$(( $(date +%s) - t0 ))" > $O/rc.txt
grep -a "Maximum resident" $O/time.log >> $O/rc.txt
grep -av '^\*\|Transferr\|^\s*$\|^\$ \|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log
tail -c 3000 $O/time.log > $O/time_tail.log
aws s3 cp --only-show-errors --recursive $O $R/out/$V/$N/ --exclude "*.step" --exclude "convert.log" --exclude "time.log" --exclude "*.png"
rm -f $O/*.step
