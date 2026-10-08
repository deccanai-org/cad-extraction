#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; mkdir -p $W/fix; cd $W
export AWS_DEFAULT_REGION=ap-south-1
for f in fullpath.py job_full_coord.sh models2.json; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/$f .; done
for f in db1bolts.py db1step.py db1bolts_guardonly.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/fix/$f fix/; done
setsid nohup bash job_full_coord.sh > job_full_coord.out 2>&1 < /dev/null &
sleep 5; cat job_full_coord.out; echo started $(date -u)
