#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; mkdir -p $D && cd $D
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x/ $D/
setsid nohup bash $D/job.sh sync > $D/job_sync.log 2>&1 < /dev/null &
sleep 2; echo started; ls -la $D; cat $D/progress.txt 2>/dev/null | tail -3
