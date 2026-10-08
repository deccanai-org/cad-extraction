#!/bin/bash
cd /work/agentwork/audit-ifc
for i in 281ab275e7922d27 83b1b55619e6c2a1 ab2cbaa2225f367a d615945ae74d80df; do rm -f out/${i}*.json; done
setsid nohup taskset -c 46-63 nice -n 5 /opt/conv/env/bin/python scan2.py --big-only --big-procs 4 --ids 281ab275e7922d27,83b1b55619e6c2a1,ab2cbaa2225f367a,d615945ae74d80df > rerun4.log 2>&1 < /dev/null &
echo started $!
