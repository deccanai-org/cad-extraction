#!/bin/bash
cd /work/agentwork/audit-ifc
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/proofs2.py proofs2.py
setsid nohup taskset -c 46-63 nice -n 5 /opt/conv/env/bin/python proofs2.py 7a75aa3213eaf457 > proofs2.log 2>&1 < /dev/null &
echo started $!
free -g | head -2; uptime
