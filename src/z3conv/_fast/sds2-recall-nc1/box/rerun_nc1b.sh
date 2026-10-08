#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/nc1_holes_check.py nc1_holes_check.py.new && mv nc1_holes_check.py.new nc1_holes_check.py
mv out/nc1 out/nc1_v2_$(date +%H%M) && mkdir -p out/nc1
setsid nohup bash $W/bg.sh nc1v3 /opt/conv/env/bin/python $W/run_jobs.py --phase nc1 --workers 6 --tag nc1v3 > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
for j in 7d979650 723d542e; do timeout 30 /opt/conv/env/bin/python explain.py $j 2>&1 | grep -E "role plate|count_equal|missing_holes  .*PL" | head -8; done
