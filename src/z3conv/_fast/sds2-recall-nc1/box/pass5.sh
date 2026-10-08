#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W
mv out/nc1 out/nc1_v4_$(date +%H%M) && mkdir -p out/nc1
/opt/conv/env/bin/python run_jobs.py --phase nc1 --workers 6 --tag nc1v5
/opt/conv/env/bin/python aggregate.py > out/aggregate_nc1v5.txt 2>&1
echo pass5 done
