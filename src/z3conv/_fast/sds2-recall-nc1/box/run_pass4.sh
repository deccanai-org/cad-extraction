#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && for f in run_jobs.py pass4.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/$f $f.new && mv $f.new $f; done
setsid nohup bash $W/bg.sh pass4 bash $W/pass4.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo started; uptime
