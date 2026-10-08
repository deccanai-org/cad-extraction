#!/bin/bash
SLUG=coverage-regression
W=/work/agentwork/$SLUG/ab
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
mkdir -p $W && cd $W
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$SLUG/ab/ . --only-show-errors
ls -la . jobs | head -40
setsid nohup bash ab_run.sh > ab_run.out 2>&1 < /dev/null &
P=$!; echo $P > ab_run.pid
setsid nohup bash -c "while kill -0 $P 2>/dev/null; do for f in build_ovl.log phase1.log phase2.log ab_run.out; do [ -f \$f ] && aws s3 cp --only-show-errors \$f $OUTS/ab/\$f; done; sleep 60; done" > /dev/null 2>&1 < /dev/null &
echo started $P
sleep 45; cat ab_run.out; cat build_ovl.log 2>/dev/null | tail -20
