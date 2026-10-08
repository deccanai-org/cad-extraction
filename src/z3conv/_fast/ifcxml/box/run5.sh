#!/bin/bash
cd /work/agentwork/ifcxml
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/job5.sh job5.sh --only-show-errors
rm -f job5.log
setsid nohup bash job5.sh > job5.out 2>&1 < /dev/null &
sleep 1; echo "job5 started $(cat job5.pid)"
