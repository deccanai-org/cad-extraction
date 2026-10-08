#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
for p in $(pgrep -f "$W/runana2.py t553w "); do pkill -TERM -P $p; kill $p; done
sleep 2; pkill -f "sds2_to_step.py.*j2/out/t553w/"; sleep 2
for f in w553b.tgz ids_t2.txt; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/$f $J/$f; done
rm -rf $J/w553b && mkdir -p $J/w553b && tar xzf $J/w553b.tgz -C $J/w553b
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py t2w $J/ids_t2.txt conv:$J/w553b/sds2-step-pipeline 6 130 > $J/t2w.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 30; cat $J/t2w.out; ps -eo args | grep -c "j2/out/t2w"
