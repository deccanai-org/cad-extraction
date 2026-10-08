#!/bin/bash
# run_one.sh VER JOBDIR : convert with pipeline VER (v4|v5) exactly like the fleet worker command -> /data/out/VER/<job>/
V=$1; J=$2; N=$(basename "$J"); O=/data/out/$V/$N; rm -rf $O; mkdir -p $O
# memory gate: never start a conversion with < 10 GB available (the first box thrashed at 18 in parallel)
while [ "$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)" -lt 10 ]; do sleep 15; done
PY=/opt/conv/sds2env/bin/python
if [ "$V" = v4 ]; then P=/opt/conv/sds2-v4/sds2-step-pipeline; else P=/opt/conv/$V/sds2-step-pipeline; fi
export PYTHONUNBUFFERED=1 MPLBACKEND=Agg LD_PRELOAD=/opt/conv/sds2env/lib/libexpat.so.1
cd $O; t0=$(date +%s)
timeout 7200 $PY -u $P/decode/sds2_to_step.py "$J" -o $O/${N}_stage2.step --stage 2 --verify > $O/convert.log 2>&1
echo "rc=$? wall=$(( $(date +%s) - t0 ))" > $O/rc.txt
grep -av '^\*\|Transferr\|^\s*$\|^\$ \|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage2.log
aws s3 cp --only-show-errors --recursive $O s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress3/$V/$N/ --exclude "*.step" --exclude "convert.log"
