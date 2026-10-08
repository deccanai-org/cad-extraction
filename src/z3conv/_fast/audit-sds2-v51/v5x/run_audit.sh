#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; mkdir -p $D && cd $D
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x/ $D/
MODE=${MODE:-audit}
setsid nohup bash $D/job.sh $MODE > $D/job_$MODE.log 2>&1 < /dev/null &
PID=$!
for i in $(seq 1 30); do sleep 3; kill -0 $PID 2>/dev/null || break; done
tail -5 $D/progress.txt; echo ---; tail -40 $D/audit.log 2>/dev/null
