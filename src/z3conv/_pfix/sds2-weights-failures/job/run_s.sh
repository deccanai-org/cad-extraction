#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_s.txt $W/ids_s.txt
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp9s $W/ids_s.txt conv:$W/p9/sds2-step-pipeline 2 40 > $W/rp9s.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
