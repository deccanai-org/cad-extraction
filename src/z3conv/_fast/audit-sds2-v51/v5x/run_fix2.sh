#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; cd $D && rm -rf $D/fixes/base
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x/ $D/
sha256sum $D/fixes/base/*.py $D/fixes/convfleet.py $D/fixes/worker.py $D/fixes/build_index.py
setsid nohup bash $D/fix_job.sh > $D/fix_job.log 2>&1 < /dev/null &
PID=$!
for i in $(seq 1 38); do sleep 3; kill -0 $PID 2>/dev/null || break; done
tail -3 $D/progress.txt; grep -E "EXPECT|rc=" $D/fixes/test.log; tail -2 $D/fixes/repair_dryrun.err
