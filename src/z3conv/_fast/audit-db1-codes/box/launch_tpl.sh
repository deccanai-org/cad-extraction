#!/bin/bash
W=/work/agentwork/audit-db1-codes; mkdir -p $W/logs && cd $W
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-db1-codes/ . --only-show-errors --exclude "kits/*" --exclude "*.md"
[ -d kits/i ] || aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-db1-codes/kits/ kits/ --only-show-errors
setsid nohup bash phase.sh __ARGS__ > logs/__PH__.out 2>&1 < /dev/null &
echo "launched __PH__ pid $!"; sleep 2; cat logs/__PH__.status 2>/dev/null; uptime
