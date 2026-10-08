#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_ve2.txt $W/ids_ve2.txt
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/runana.py $W/runana.py
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py ve54 $W/ids_ve2.txt conv:$W/v54/sds2-step-pipeline 2 30 > $W/ve54.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
