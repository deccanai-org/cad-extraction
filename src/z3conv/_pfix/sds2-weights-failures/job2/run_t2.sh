#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/runana2.py $W/runana2.py
rm -f $J/full_*.json
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py t553w $J/ids_t.txt conv:$J/w553a/sds2-step-pipeline 5 110 > $J/t553w.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 45; cat $J/t553w.out; tail -3 $J/t553w.runlog; ls $J/out/t553w 2>/dev/null
