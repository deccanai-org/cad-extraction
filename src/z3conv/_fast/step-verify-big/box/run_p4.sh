#!/bin/bash
# BOX-A: phase 4 = the remaining 131 flagged models (no source inventory), smallest first, nice 19 (idle CPU only), <= 14 threads.
# Records land in s3 agentwork/step-verify-big/final/{results,detail}/ as each model finishes; status_p4.json every 60 s.
# Stop: kill $(cat /work/agentwork/step-verify-big/jobq_p4.pid); pkill -f 'step-verify-big/pkg/step_verify_big.py|pkg/step_verify_big.py in/Q'
cd /work/agentwork/step-verify-big
P=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big
if [ -f jobq_p4.pid ] && kill -0 $(cat jobq_p4.pid) 2>/dev/null; then echo "already running: $(cat jobq_p4.pid)"; exit 0; fi
for f in jobq.py tasks_p4.json step_verify_big.py to_final_result.py; do aws s3 cp --only-show-errors $P/$f pkg/$f.new && mv pkg/$f.new pkg/$f; done
grep -m1 "^VERSION" pkg/step_verify_big.py
setsid nohup nice -n 10 /opt/conv/env/bin/python pkg/jobq.py pkg/tasks_p4.json --s3 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big --threads 14 --mem-gb 60 --tag p4 > jobq_p4.log 2>&1 < /dev/null &
echo $! > jobq_p4.pid; sleep 10; echo "pid $(cat jobq_p4.pid)"; tail -3 jobq_p4.log; ls logs | grep -c Q0
