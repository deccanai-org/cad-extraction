#!/bin/bash
# canary worker: V = rc | v559, own job list, run once per id, exits when done
V=__V__; JL=__JL__; IDS=__IDS__
C=/opt/conv/canary/$V; mkdir -p $C/sds2 /scratch/conv/canary_$V
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/test/sds2canary/$V/ $C/sds2/
cd $C/sds2 && CONV_HOME=/opt/conv CONV_WORK=/scratch/conv/canary_$V CONV_DONE=$C/DONE CONV_JOBS_KEY=ctl:sds2/$JL CONV_NO_EXTRA=1 \
  CONV_RERUN=$IDS CONV_RERUN_ONCE=1 CONV_EXIT_WHEN_DONE=1 CONV_SLOTS=6 nohup /opt/conv/sds2env/bin/python $C/sds2/worker.py > $C/worker.log 2>&1 &
sleep 60; tail -n 5 $C/worker.log
