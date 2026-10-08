#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_csu.txt $W/ids_csu.txt
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py csu54 $W/ids_csu.txt conv:$W/v54/sds2-step-pipeline 1 30 > $W/csu54.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
