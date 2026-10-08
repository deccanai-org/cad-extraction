#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && for f in nc1_holes_check.py run_jobs.py aggregate.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/$f $f.new && mv $f.new $f; done
mv out/nc1 out/nc1_v1_$(date +%H%M) && mkdir -p out/nc1
setsid nohup bash $W/bg.sh nc1v2 /opt/conv/env/bin/python $W/run_jobs.py --phase nc1 --workers 6 --tag nc1v2 > /dev/null 2>&1 < /dev/null &
sleep 1; echo started; ls out
