#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
for f in p7.tgz ids_rp7.txt ids_rp7t.txt piece_table_v5work.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/$f $W/$f; done
rm -rf $W/p7 $W/p7t && mkdir -p $W/p7 $W/p7t && tar xzf $W/p7.tgz -C $W/p7 && tar xzf $W/p7.tgz -C $W/p7t && cp $W/piece_table_v5work.py $W/p7t/sds2-step-pipeline/decode/piece_table.py
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp7 $W/ids_rp7.txt conv:$W/p7/sds2-step-pipeline 4 90 > $W/rp7.out 2>&1" > /dev/null 2>&1 < /dev/null &
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp7t $W/ids_rp7t.txt conv:$W/p7t/sds2-step-pipeline 1 30 > $W/rp7t.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
