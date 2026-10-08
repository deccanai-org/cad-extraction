#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/run_rod2.sh .
setsid nohup bash run_rod2.sh > run_rod2.out 2>&1 < /dev/null &
echo launched
ps -eo pid,args | grep -c "sds2_to_step.py" 
