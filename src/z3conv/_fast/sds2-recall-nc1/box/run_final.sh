#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/final.sh final.sh && chmod +x final.sh
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/aggregate.py aggregate.py.new && mv aggregate.py.new aggregate.py
setsid nohup bash $W/bg.sh final bash $W/final.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo started; cat logs/pipe.pid logs/conv.pid
