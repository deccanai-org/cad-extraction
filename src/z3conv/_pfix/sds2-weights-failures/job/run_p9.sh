#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
for t in p5 rp8 rp8t; do for p in $(pgrep -f "$W/runana.py $t "); do pkill -TERM -P $p; kill $p; done; done
sleep 2; pkill -f "wdump.py $W/p5/"; pkill -f "sds2_to_step.py.*out/rp8"; pkill -f "fetch.py $W/tmp" -P 1 2>/dev/null; sleep 2
for f in p9.tgz ids_p9.txt ids_rp7.txt ids_rp7t.txt piece_table_v5work.py wdump.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/$f $W/$f; done
rm -rf $W/p9 $W/p9t && mkdir -p $W/p9 $W/p9t && tar xzf $W/p9.tgz -C $W/p9 && tar xzf $W/p9.tgz -C $W/p9t && cp $W/piece_table_v5work.py $W/p9t/sds2-step-pipeline/decode/piece_table.py
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py p9 $W/ids_p9.txt ana:$W/p9/sds2-step-pipeline/decode 7 80 > $W/p9.out 2>&1" > /dev/null 2>&1 < /dev/null &
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp9 $W/ids_rp7.txt conv:$W/p9/sds2-step-pipeline 3 80 > $W/rp9.out 2>&1" > /dev/null 2>&1 < /dev/null &
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp9t $W/ids_rp7t.txt conv:$W/p9t/sds2-step-pipeline 1 30 > $W/rp9t.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 1; ps -eo args | grep -c "runana.py p5\|runana.py rp8"
echo started
