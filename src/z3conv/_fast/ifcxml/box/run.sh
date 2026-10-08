#!/bin/bash
# SSM entry: fetch the staged ifcxml job and start it detached
set -e
mkdir -p /work/agentwork/ifcxml && cd /work/agentwork/ifcxml
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/ . --only-show-errors
if [ -f job.pid ] && kill -0 $(cat job.pid) 2>/dev/null; then echo "already running pid $(cat job.pid)"; exit 0; fi
rm -f job.done
setsid nohup bash job.sh > job.out 2>&1 < /dev/null &
sleep 2
echo "started pid $(cat job.pid 2>/dev/null)"; ls -la | head -30
