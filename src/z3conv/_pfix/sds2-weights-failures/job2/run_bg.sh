#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
for p in $(pgrep -f "$W/runana.py rb54 "); do pkill -TERM -P $p; kill $p; done; sleep 2; pkill -f "out/rb54/436d09"; sleep 1
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/ids_bg.txt $J/
setsid nohup bash -c "SDS2_ASSEMBLY_CHECK_MAX=0 /opt/conv/env/bin/python $W/runana2.py bgw $J/ids_bg.txt conv:$J/w553b/sds2-step-pipeline 1 50 > $J/bgw.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 5; cat $J/bgw.out; pgrep -f "out/rb54" | wc -l
