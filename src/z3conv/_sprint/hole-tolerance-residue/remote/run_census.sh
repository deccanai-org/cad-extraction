#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; mkdir -p $W; cd $W
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/ .
ls -la
setsid nohup bash job_census.sh > job_census.out 2>&1 < /dev/null &
sleep 5; cat job_census.out; echo started $(date -u)
