#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/ids_wr.txt $J/
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py wrw $J/ids_wr.txt conv:$J/w553b/sds2-step-pipeline 3 60 > $J/wrw.out 2>&1" > /dev/null 2>&1 < /dev/null &
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py wrb $J/ids_wr.txt conv:$J/b553/sds2-step-pipeline 2 45 > $J/wrb.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 10; cat $J/wrw.out $J/wrb.out
