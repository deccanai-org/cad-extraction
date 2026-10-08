#!/bin/bash
mkdir -p /work/agentwork/audit-ifc && cd /work/agentwork/audit-ifc
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/ . 
/opt/conv/env/bin/python apitest.py 2>&1 | head -30
echo ---- 084
/opt/conv/ifc84/bin/python apitest.py 2>&1 | head -12
