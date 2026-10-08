#!/bin/bash
# BOX-A: restart phase 4 with the regenerated list (current index, suffix-aware inventory keys, done models excluded);
# rebuild 1924e526's record with its .v6 inventory (the first list looked for the un-suffixed one)
cd /work/agentwork/step-verify-big
P=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big
F=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final
if [ -f jobq_p4.pid ]; then kill $(cat jobq_p4.pid) 2>/dev/null; fi
sleep 2; pkill -f 'pkg/step_verify_big.py in/Q' ; sleep 3; pkill -9 -f 'pkg/step_verify_big.py in/Q'
rm -rf in/Q* wd/Q*
ID=1924e526e9c87d2cebea8a322c08a0eb80b1a2e177c8b686cd8a4d85934f75a5
aws s3 cp --only-show-errors s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/ifc/detail/$ID.v6.src_parts.jsonl.gz ref/Q005_1924e526.src_parts.jsonl.gz
/opt/conv/env/bin/python pkg/to_final_result.py out/Q005_1924e526/s_x24.json out/Q005_1924e526/s_x24.parts.jsonl.gz --pipeline ifc --model-id $ID \
   --step-key cad-disk-extract/zenitude-data-3/conversions/ifc-step/$ID.v6.step --src-parts ref/Q005_1924e526.src_parts.jsonl.gz --grade-join pkg/grade_join.py \
   -o out/Q005_1924e526/final_readback_x24.json > out/Q005_1924e526/final_readback_x24.json.log 2>&1
cat out/Q005_1924e526/final_readback_x24.json.log
aws s3 cp --only-show-errors out/Q005_1924e526/final_readback_x24.json $F/results/f-ifc-${ID:0:40}-readback.json
mv logs logs_p4a 2>/dev/null; mkdir -p logs; cp -r logs_p4a/* logs/ 2>/dev/null
mv status_p4.json status_p4a.json 2>/dev/null
for f in tasks_p4.json; do aws s3 cp --only-show-errors $P/$f pkg/$f.new && mv pkg/$f.new pkg/$f; done
setsid nohup nice -n 10 /opt/conv/env/bin/python pkg/jobq.py pkg/tasks_p4.json --s3 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big --threads 14 --mem-gb 60 --tag p4 > jobq_p4.log 2>&1 < /dev/null &
echo $! > jobq_p4.pid; sleep 10; echo "pid $(cat jobq_p4.pid)"; tail -2 jobq_p4.log
ps -eo pid,args | grep "step_verify_big.py in/Q" | grep -v grep | cut -c1-120 | head -4
