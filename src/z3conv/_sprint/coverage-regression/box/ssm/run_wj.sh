#!/bin/bash
# coverage-regression: Windows-STEP Tekla-id join (box job, background)
SLUG=coverage-regression
W=/work/agentwork/$SLUG/wj
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
mkdir -p $W && cd $W
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$SLUG/wj/ . --only-show-errors
ls -la
PAR=10 setsid nohup /opt/conv/env/bin/python run_wj.py > run_wj.log 2>&1 < /dev/null &
P=$!
echo $P > run_wj.pid
setsid nohup bash -c "while kill -0 $P 2>/dev/null; do aws s3 cp --only-show-errors run_wj.log $OUTS/logs/run_wj.log; sleep 45; done; aws s3 cp --only-show-errors run_wj.log $OUTS/logs/run_wj.log" > /dev/null 2>&1 < /dev/null &
echo started pid $P
sleep 20; cat run_wj.log
