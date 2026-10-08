#!/bin/bash
cd /work/agentwork/audit-ifc
setsid nohup taskset -c 46-63 nice -n 5 /opt/conv/env/bin/python class1check.py 6 > c1.log 2>&1 < /dev/null &
echo started $!
