#!/bin/bash
# base pass: wait for the Disk-1/2 NC1 resolution, ground-truth inventory (prep), NC1 + IFC checks on the fleet's STEPs, report
W=/work/agentwork/sds2-recall-nc1
cd $W
P=$(cat logs/d12b.pid 2>/dev/null)
while [ -n "$P" ] && kill -0 $P 2>/dev/null; do sleep 15; done
echo "d12b finished $(date -u)"
/opt/conv/env/bin/python run_jobs.py --phase prep --workers 12
/opt/conv/env/bin/python run_jobs.py --phase nc1,ifc --workers 8 --ifc-workers 5 --ifc-threads 2 --tag base
/opt/conv/env/bin/python aggregate.py
echo "pipeline done $(date -u)"
