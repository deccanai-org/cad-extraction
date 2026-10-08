#!/bin/bash
W=/work/agentwork/sds2-weights-failures; mkdir -p $W; cd $W
aws s3 cp --recursive --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ $W/
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures
setsid nohup bash -c "bash $W/setup.sh > $W/setup.out 2>&1; aws s3 cp --only-show-errors $W/setup.out $R/setup.out; /opt/conv/env/bin/python $W/runana.py pilot $W/pilot_ids.txt ana:$W/v54/sds2-step-pipeline/decode 8 100 > $W/pilot.out 2>&1; aws s3 cp --only-show-errors $W/pilot.runlog $R/pilot.runlog" > /dev/null 2>&1 < /dev/null &
echo started $!
