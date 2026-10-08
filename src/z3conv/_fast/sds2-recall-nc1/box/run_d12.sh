#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/resolve_d12.py .
cp -n $W/inv/pairs.json $W/inv/pairs_orig.json
setsid nohup bash $W/bg.sh d12 /opt/conv/env/bin/python $W/resolve_d12.py > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
