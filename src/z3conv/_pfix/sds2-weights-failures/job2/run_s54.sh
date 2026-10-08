#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
for f in w54b.tgz ids_s54.txt; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/$f $J/; done
rm -rf $J/w54b && mkdir -p $J/w54b && tar xzf $J/w54b.tgz -C $J/w54b
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py s54 $J/ids_s54.txt conv:$J/w54b/sds2-step-pipeline 3 30 > $J/s54.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 3; cat $J/s54.out
