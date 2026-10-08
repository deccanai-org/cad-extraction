#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
for f in job_v2_coord.sh fullpath.py runjob2.py harness2.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/$f .; done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/fix/db1step.py fix/db1step.py
md5sum fix/db1step.py fix/db1bolts.py; pgrep -af "runjob2|fullpath" | head -3
setsid nohup bash job_v2_coord.sh > job_v2_coord.out 2>&1 < /dev/null &
sleep 4; cat job_v2_coord.out; uptime; echo started $(date -u)
