#!/bin/bash
# BOX-A: start the step-verify-big job queue (setsid nohup; results -> s3 agentwork/step-verify-big/)
set -e
W=/work/agentwork/step-verify-big
mkdir -p $W && cd $W
if [ -f jobq_main.pid ] && kill -0 $(cat jobq_main.pid) 2>/dev/null; then echo "already running: $(cat jobq_main.pid)"; exit 0; fi
rm -rf pkg && mkdir -p pkg
aws s3 cp --recursive --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big/ pkg/
setsid nohup /opt/conv/env/bin/python pkg/jobq.py pkg/tasks_main.json --s3 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big --threads 20 --mem-gb 150 --tag main > jobq_main.log 2>&1 < /dev/null &
echo $! > jobq_main.pid
sleep 20
echo "pid $(cat jobq_main.pid)"; cat jobq_main.log | tail -5
ls logs | head; uptime
ps -eo pid,pcpu,rss,etime,args | grep -E "step_check|step_verify_big|aws s3" | grep -v grep | cut -c1-160 | head -20
