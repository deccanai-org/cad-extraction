#!/bin/bash
W=/work/agentwork/sds2-weights-failures; cd $W
for f in p8.tgz ids_rp7.txt ids_rp7t.txt piece_table_v5work.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/$f $W/$f; done
rm -rf $W/p8 $W/p8t && mkdir -p $W/p8 $W/p8t && tar xzf $W/p8.tgz -C $W/p8 && tar xzf $W/p8.tgz -C $W/p8t && cp $W/piece_table_v5work.py $W/p8t/sds2-step-pipeline/decode/piece_table.py
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp8 $W/ids_rp7.txt conv:$W/p8/sds2-step-pipeline 3 80 > $W/rp8.out 2>&1" > /dev/null 2>&1 < /dev/null &
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py rp8t $W/ids_rp7t.txt conv:$W/p8t/sds2-step-pipeline 1 30 > $W/rp8t.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
