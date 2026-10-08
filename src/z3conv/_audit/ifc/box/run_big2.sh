#!/bin/bash
cd /work/agentwork/audit-ifc
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/scan2.py scan2.py
setsid nohup taskset -c 46-63 nice -n 5 /opt/conv/env/bin/python scan2.py --big-only --reverse --big-procs 6 > scan2.log 2>&1 < /dev/null &
echo started $!
sleep 3; head -3 scan2.log; ls out | wc -l
