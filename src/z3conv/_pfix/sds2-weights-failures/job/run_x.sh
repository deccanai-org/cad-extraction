#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
for t in rb54x rp9x; do for p in $(pgrep -f "$W/runana.py $t "); do pkill -TERM -P $p; kill $p; done; done
sleep 2; pkill -f "sds2_to_step.py.*out/rb54x"; sleep 1
for f in ids_x.txt ids_xb.txt; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/$f $W/$f; done
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rb54x $W/ids_xb.txt conv:$W/v54/sds2-step-pipeline 1 20 > $W/rb54x.out 2>&1; /opt/conv/env/bin/python $W/runana.py rp9x $W/ids_x.txt conv:$W/p9/sds2-step-pipeline 1 20 > $W/rp9x.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo restarted
