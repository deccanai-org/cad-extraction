#!/bin/bash
# BOX-A: tool update (2026-10-02b: per-part nonpos field; same signals) + sampling-emulation test queue (<= 4 threads)
cd /work/agentwork/step-verify-big
P=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big
aws s3 cp --only-show-errors $P/step_verify_big.py pkg/step_verify_big.py.new && mv pkg/step_verify_big.py.new pkg/step_verify_big.py
for f in tasks_sampling.json spec_sampling.json; do aws s3 cp --only-show-errors $P/$f pkg/$f; done
grep -m1 "^VERSION" pkg/step_verify_big.py
setsid nohup /opt/conv/env/bin/python pkg/jobq.py pkg/tasks_sampling.json --s3 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big --threads 4 --mem-gb 16 --tag sampling > jobq_sampling.log 2>&1 < /dev/null &
echo $! > jobq_sampling.pid; sleep 5; echo "pid $(cat jobq_sampling.pid)"; ps -eo pid,args | grep "max-check 1" | grep -v grep | cut -c1-150 | head
