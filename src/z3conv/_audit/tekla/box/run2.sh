#!/bin/bash
mkdir -p /work/agentwork/tekla-audit && cd /work/agentwork/tekla-audit
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/tekla-audit/agg_win.py . --only-show-errors
setsid nohup /opt/conv/env/bin/python agg_win.py > agg_win.log 2>&1 < /dev/null &
echo "started pid $!"; sleep 3; cat agg_win.log
