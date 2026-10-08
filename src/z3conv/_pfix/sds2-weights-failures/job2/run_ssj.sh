#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
for f in ids_ssj.txt piece_table_v5work.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/$f $J/; done
rm -rf $J/w553t && mkdir -p $J/w553t && tar xzf $J/w553b.tgz -C $J/w553t && cp $J/piece_table_v5work.py $J/w553t/sds2-step-pipeline/decode/piece_table.py
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py ssjw $J/ids_ssj.txt conv:$J/w553t/sds2-step-pipeline 2 60 > $J/ssjw.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 3; cat $J/ssjw.out
