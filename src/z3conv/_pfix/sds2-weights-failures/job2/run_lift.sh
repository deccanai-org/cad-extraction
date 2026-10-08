#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/ids_lift.txt $J/
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py liftw $J/ids_lift.txt conv:$J/w553b/sds2-step-pipeline 2 20 > $J/liftw.out 2>&1; /opt/conv/env/bin/python $W/runana2.py liftb $J/ids_lift.txt conv:$J/b553/sds2-step-pipeline 2 20 > $J/liftb.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 3; cat $J/liftw.out
