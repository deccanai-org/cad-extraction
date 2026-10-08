#!/bin/bash
C=/opt/conv/canary/base; mkdir -p $C/sds2 /scratch/conv/canary_base
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/test/sds2canary/base/ $C/sds2/
systemctl stop z3canary-base 2>/dev/null
systemd-run --unit=z3canary-base --collect --working-directory=$C/sds2   --setenv=CONV_HOME=/opt/conv --setenv=CONV_WORK=/scratch/conv/canary_base --setenv=CONV_DONE=$C/DONE   --setenv=CONV_JOBS_KEY=ctl:canary_base.json --setenv=CONV_NO_EXTRA=1 --setenv=CONV_RERUN=0535bdbbe63db0f7008b7218,4c381a54360ac7d2dc367923,e222e6b62af206b310e8619f,f3482a0d55594d8d8577f98e,c053564dec23e0c71d377145   --setenv=CONV_RERUN_ONCE=1 --setenv=CONV_EXIT_WHEN_DONE=1 --setenv=CONV_SLOTS=6 --setenv=CONV_NO_RELOAD=1 --setenv=AWS_DEFAULT_REGION=ap-south-1   /bin/bash -c "/opt/conv/sds2env/bin/python $C/sds2/worker.py >> $C/worker.log 2>&1"
sleep 45; systemctl is-active z3canary-base; tail -n 4 $C/worker.log | cut -c1-200
