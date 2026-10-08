#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/ids_nf.txt $J/
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py nf553 $J/ids_nf.txt ana:$J/w553a/sds2-step-pipeline/decode 4 50 > $J/nf553.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 5; cat $J/nf553.out; uptime
