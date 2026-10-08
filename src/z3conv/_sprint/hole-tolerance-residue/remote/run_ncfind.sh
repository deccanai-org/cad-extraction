#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/nc_find.py .
timeout 100 /opt/conv/env/bin/python nc_find.py models.json nc_find.json 2>&1 | tail -5
aws s3 cp --quiet nc_find.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S/nc_find.json
tail -3 census.log; uptime
