#!/bin/bash
# re-run the analysis with the patched decode (p2) on a job list
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/p2.tgz $W/p2.tgz
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/wdump.py $W/wdump.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_p2.txt $W/ids_p2.txt
rm -rf $W/p2 && mkdir -p $W/p2 && tar xzf $W/p2.tgz -C $W/p2
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py p2 $W/ids_p2.txt ana:$W/p2/sds2-step-pipeline/decode 6 60 > $W/p2.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
