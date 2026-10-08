#!/bin/bash
set -e
mkdir -p /work/agentwork/tekla-audit && cd /work/agentwork/tekla-audit
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/tekla-audit/ . --only-show-errors
setsid nohup /opt/conv/env/bin/python agg.py > agg.log 2>&1 < /dev/null &
echo "started pid $!"
sleep 5; cat agg.log; uptime
