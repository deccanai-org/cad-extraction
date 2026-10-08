#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/run_jobs.py run_jobs.py.new && mv run_jobs.py.new run_jobs.py
mkdir -p out/ifc
setsid nohup bash $W/bg.sh ifcA /opt/conv/env/bin/python $W/run_jobs.py --phase ifc --no-digest --workers 4 --tag ifcA > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
