#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/conv_jobs.py .
uptime; free -g | head -2
setsid nohup bash $W/bg.sh conv /opt/conv/env/bin/python $W/conv_jobs.py $W/inv/conv_todo.json --slots 5 --timeout 5400 > /dev/null 2>&1 < /dev/null &
sleep 2; echo started
