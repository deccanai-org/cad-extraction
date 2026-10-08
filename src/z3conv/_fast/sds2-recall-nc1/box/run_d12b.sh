#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/resolve_d12.py .
setsid nohup bash $W/bg.sh d12b /opt/conv/env/bin/python $W/resolve_d12.py --all > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
