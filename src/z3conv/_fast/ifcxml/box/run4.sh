#!/bin/bash
cd /work/agentwork/ifcxml
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/job4.sh job4.sh --only-show-errors
if [ -f job4.pid ] && kill -0 $(cat job4.pid) 2>/dev/null; then echo "job4 already running"; exit 0; fi
rm -f job4.done job4.log
setsid nohup bash job4.sh > job4.out 2>&1 < /dev/null &
sleep 1; echo "job4 started $(cat job4.pid)"; tail -4 harness.log
