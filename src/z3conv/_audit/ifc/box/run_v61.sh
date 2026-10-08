#!/bin/bash
cd /work/agentwork/audit-ifc
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/verify61.py verify61.py
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/v61ids.json v61ids.json
setsid nohup taskset -c 46-63 /opt/conv/env/bin/python verify61.py "$(cat v61ids.json)" > v61.log 2>&1 < /dev/null &
echo started $!
