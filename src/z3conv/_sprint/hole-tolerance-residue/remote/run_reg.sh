#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p fix
for f in runjob.py harness2.py models2.json fullpath.py job_reg.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/$f .; done
for f in db1bolts.py db1step.py db1bolts_guardonly.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/fix/$f fix/; done
ls -la fix; pgrep -f "runjob.py" -a | head -3
setsid nohup bash job_reg.sh > job_reg.out 2>&1 < /dev/null &
sleep 8; cat job_reg.out; echo started $(date -u)
