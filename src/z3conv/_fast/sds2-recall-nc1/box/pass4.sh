#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W
/opt/conv/env/bin/python run_jobs.py --phase prep --workers 10
mv out/nc1 out/nc1_v3_$(date +%H%M) && mkdir -p out/nc1
/opt/conv/env/bin/python run_jobs.py --phase nc1 --workers 6 --tag nc1v4
/opt/conv/env/bin/python aggregate.py > out/aggregate_nc1v4.txt 2>&1
echo pass4 done
