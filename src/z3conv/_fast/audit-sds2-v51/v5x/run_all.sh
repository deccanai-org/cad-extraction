#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; mkdir -p $D && cd $D
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x/ $D/
setsid nohup bash $D/job.sh all > $D/job_all.log 2>&1 < /dev/null &
PID=$!
for i in $(seq 1 36); do sleep 3; kill -0 $PID 2>/dev/null || break; done
tail -6 $D/progress.txt; echo ---; grep -A40 '"regression_pairs"' $D/audit.log | head -60; tail -3 $D/job_all.log
