#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/run_base.sh .
setsid nohup bash run_base.sh > run_base.out 2>&1 < /dev/null &
echo launched; free -g | head -2; uptime
