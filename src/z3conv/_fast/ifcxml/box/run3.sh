#!/bin/bash
cd /work/agentwork/ifcxml
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/job3.sh job3.sh --only-show-errors
if [ -f job3.pid ] && kill -0 $(cat job3.pid) 2>/dev/null; then echo "job3 already running"; exit 0; fi
rm -f job3.done job3.log
setsid nohup bash job3.sh > job3.out 2>&1 < /dev/null &
sleep 1; echo "job3 started $(cat job3.pid)"; tail -5 harness.log 2>/dev/null; which patch || echo "no patch binary"
