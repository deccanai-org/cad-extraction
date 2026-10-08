#!/bin/bash
set -e
mkdir -p /work/agentwork/audit-sds2-pipeline && cd /work/agentwork/audit-sds2-pipeline
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-pipeline/ . --quiet --region ap-south-1
ls -la
rm -f progress.txt
setsid nohup /opt/conv/env/bin/python audit_sds2.py > run.log 2>&1 < /dev/null &
echo "started pid $!"
sleep 20; tail -5 run.log
