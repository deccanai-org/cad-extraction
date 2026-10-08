#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
P=$(pgrep -f "runjob.py models.json kit_i census" | head -1)
if [ -n "$P" ]; then PG=$(ps -o pgid= -p $P | tr -d ' '); echo "killing my pgid $PG"; ps -o pid,args -g $PG | head -30 | cut -c1-120; kill -- -$PG; fi
sleep 2
rm -f census/kit_i/*.err
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/job_census.sh .
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/nc_find.py .
ls census/kit_i/ | wc -l
setsid nohup bash job_census.sh > job_census.out 2>&1 < /dev/null &
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
setsid nohup bash -c "/opt/conv/env/bin/python nc_find.py models.json nc_find.json > nc_find.log 2>&1; aws s3 cp --quiet nc_find.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S/nc_find.json" > /dev/null 2>&1 < /dev/null &
sleep 3; ps -eo pid,nlwp,args | grep -E "harness2|nc_find|runjob" | grep -v grep | head | cut -c1-150
