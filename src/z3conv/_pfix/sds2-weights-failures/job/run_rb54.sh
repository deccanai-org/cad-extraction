#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_reg.txt $W/ids_reg.txt
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rb54 $W/ids_reg.txt conv:$W/v54/sds2-step-pipeline 3 60 > $W/rb54.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
