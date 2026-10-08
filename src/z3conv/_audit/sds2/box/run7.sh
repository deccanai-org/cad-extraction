#!/bin/bash
cd /work/agentwork/audit-sds2-pipeline
for f in d5b.py go54.sh; do aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-pipeline/$f . --quiet --region ap-south-1; done
setsid nohup bash go54.sh > go54.out 2>&1 < /dev/null &
echo started $!
