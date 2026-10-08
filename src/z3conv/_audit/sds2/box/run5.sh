#!/bin/bash
cd /work/agentwork/audit-sds2-pipeline
for f in misc_run.py misc_probe.py; do aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-pipeline/$f . --quiet --region ap-south-1; done
setsid nohup /opt/conv/env/bin/python misc_run.py > misc_run.log 2>&1 < /dev/null &
echo started $!
