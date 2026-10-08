#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
P=$(pgrep -f "bash job_v2_coord.sh" | head -1); if [ -n "$P" ]; then PG=$(ps -o pgid= -p $P | tr -d ' '); echo "killing my v2 pgid $PG ($(ps -o pid= -g $PG | wc -l) procs)"; kill -- -$PG; fi
sleep 2
for f in job_v3_coord.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/$f .; done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/fix/db1step.py fix/db1step.py
md5sum fix/db1step.py; ls census/kit_jg/*.json | wc -l
setsid nohup bash job_v3_coord.sh > job_v3_coord.out 2>&1 < /dev/null &
sleep 4; cat job_v3_coord.out; pgrep -af "runjob2|fullpath" | cut -c1-120 | head -5; uptime
