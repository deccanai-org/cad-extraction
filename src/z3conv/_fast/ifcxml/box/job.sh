#!/bin/bash
# ifcxml stream job on the agent box: regression tests, discovery (data-3 + data-4), data-4 conversions
cd /work/agentwork/ifcxml
export PYTHONDONTWRITEBYTECODE=1
P=/opt/conv/env/bin/python
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml
echo $$ > job.pid
sync_logs() { for f in tests.log find.log conv_d4.log job.log; do [ -f $f ] && aws s3 cp $f $OUT/logs/$f --only-show-errors; done; }
( while [ ! -f job.done ]; do sync_logs; sleep 60; done ) &
echo "$(date -u +%FT%TZ) start" >> job.log
bash run_tests.sh > tests.log 2>&1
aws s3 cp work/tests/summary.json $OUT/tests_summary.json --only-show-errors
FIND_PROCS=10 FIND_THREADS=32 FIND_WORK=find $P find_inputs.py > find.log 2>&1 &
FPID=$!
$P conv_batch.py jobs_d4.json --procs 3 --tag d4 > conv_d4.log 2>&1
echo "$(date -u +%FT%TZ) conv_d4 done" >> job.log
wait $FPID
echo "$(date -u +%FT%TZ) find done" >> job.log
touch job.done
sync_logs
