#!/bin/bash
cd /work/agentwork/ifcxml
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/job2.sh job2.sh --only-show-errors
if [ -f job2.pid ] && kill -0 $(cat job2.pid) 2>/dev/null; then echo "job2 already running"; exit 0; fi
rm -f job2.done
setsid nohup bash job2.sh > job2.out 2>&1 < /dev/null &
sleep 1; echo "job2 started $(cat job2.pid)"; tail -3 conv_d4.log
