#!/bin/bash
cd /work/agentwork/audit-sds2-pipeline
rm -rf snap out/*.json out/*.gz progress.txt
aws s3 rm s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/DONE --quiet --region ap-south-1
setsid nohup /opt/conv/env/bin/python audit_sds2.py > run2.log 2>&1 < /dev/null &
echo started $!
