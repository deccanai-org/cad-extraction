#!/bin/bash
W=/work/agentwork/coverage-regression/ab
cd $W && aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/coverage-regression/abj/abj_run.sh . --only-show-errors
setsid nohup bash abj_run.sh > abj_run.out 2>&1 < /dev/null &
echo started $!; sleep 5; cat abj_run.out; uptime
