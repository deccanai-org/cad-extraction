#!/bin/bash
# conv.sh VER JOBDIR [noverify] -> /work/agentwork/sds2v54/out/VER/<job>/ (results uploaded, STEP kept local)
V=$1; J=$2; N=$(basename "$J"); W=/work/agentwork/sds2v54; O=$W/out/$V/$N
mkdir -p $O
while [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 80 ]; do sleep 20; done
export PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1 AWS_DEFAULT_REGION=ap-south-1
EX=$W/env/lib/libexpat.so.1; [ -f $EX ] && export LD_PRELOAD=$EX
VF="--verify"; [ "$3" = "noverify" ] && VF=""
cd $O; t0=$(date +%s)
timeout 10800 $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py "$J" -o $O/${N}_stage2.step --stage 2 $VF > $O/convert.log 2>&1
echo "rc=$? wall=$(( $(date +%s) - t0 ))" > $O/rc.txt
grep -av '^\*\|Transferr\|^\s*$\|^\$ \|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log
if [ "$N" = "GMS" ]; then
  $W/env/bin/python $W/v54/sds2-step-pipeline/qa/nc1_holes.py "$J" "$W/gms_gt" --manifest $O/${N}_stage2_manifest.json -o $O/nc1_holes.json > $O/nc1.log 2>&1
fi
aws s3 cp --only-show-errors --recursive $O s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/$V/$N/ --exclude "*.step" --exclude "convert.log"
