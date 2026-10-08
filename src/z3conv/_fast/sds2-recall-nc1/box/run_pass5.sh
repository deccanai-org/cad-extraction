#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/pass5.sh pass5.sh
setsid nohup bash $W/bg.sh pass5 bash $W/pass5.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
