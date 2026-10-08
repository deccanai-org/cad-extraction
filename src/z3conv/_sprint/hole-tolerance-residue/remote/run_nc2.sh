#!/bin/bash
S=hole-tolerance-residue; cd /work/agentwork/$S; export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/nc_check2.py .
timeout 110 /opt/conv/env/bin/python nc_check2.py nc_find.json nc_check2.json 2>&1 | tail -20
aws s3 cp --quiet nc_check2.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S/nc_check2.json
grep -c . reg.log; tail -3 reg.log; uptime
