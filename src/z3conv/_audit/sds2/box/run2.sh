#!/bin/bash
mkdir -p /work/agentwork/audit-sds2-pipeline && cd /work/agentwork/audit-sds2-pipeline
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-pipeline/ . --quiet --region ap-south-1
chmod +x go.sh
ls -la
setsid nohup bash go.sh > go.out 2>&1 < /dev/null &
echo "started go.sh pid $!"
