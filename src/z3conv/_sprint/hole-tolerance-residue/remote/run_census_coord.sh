#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
for f in runjob2.py harness2.py job_census_coord.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/$f .; done
ls kit_jg/db1bolts.py kit_jp/db1bolts.py && md5sum kit_jg/db1bolts.py kit_jp/db1bolts.py kit_jp/db1step.py
setsid nohup bash job_census_coord.sh > job_census_coord.out 2>&1 < /dev/null &
sleep 3; uptime; echo started $(date -u)
