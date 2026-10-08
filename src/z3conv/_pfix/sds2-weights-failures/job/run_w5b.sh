#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_w5.txt $W/ids_w5.txt
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py w5b $W/ids_w5.txt ana:$W/v54/sds2-step-pipeline/decode 3 30 > $W/w5b.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
