#!/bin/bash
# check_one.sh VER JOBDIR : v5 regression metrics for /data/out/VER/<job>/<job>_stage2.step
V=$1; J=$2; N=$(basename "$J"); O=/data/out/$V/$N
[ -f $O/${N}_stage2.step ] || exit 0
export LD_PRELOAD=/opt/conv/sds2env/lib/libexpat.so.1
timeout 5400 /opt/conv/sds2env/bin/python /opt/conv/v5/sds2-step-pipeline/qa/v5check.py "$J" $O/${N}_stage2.step -o $O/metrics.json > $O/check.log 2>&1
aws s3 cp --only-show-errors $O/metrics.json s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress2/$V/$N/metrics.json
aws s3 cp --only-show-errors $O/check.log s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress2/$V/$N/check.log
