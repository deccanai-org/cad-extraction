#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/envsetup.sh .
setsid nohup bash $W/bg.sh envsetup bash $W/envsetup.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
