#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
mkdir -p $W && cd $W
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/ .
chmod +x *.sh
setsid nohup bash $W/bg.sh inv /opt/conv/env/bin/python $W/inv_scan.py > /dev/null 2>&1 < /dev/null &
sleep 3
echo started; ls $W; cat $W/logs/inv.pid 2>/dev/null
