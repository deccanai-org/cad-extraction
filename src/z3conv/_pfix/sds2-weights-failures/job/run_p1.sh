#!/bin/bash
# re-run the analysis with the patched decode (p1) on a job list
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/p1.tgz $W/p1.tgz
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/wdump.py $W/wdump.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_p1.txt $W/ids_p1.txt
rm -rf $W/p1 && mkdir -p $W/p1 && tar xzf $W/p1.tgz -C $W/p1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py p1 $W/ids_p1.txt ana:$W/p1/sds2-step-pipeline/decode 6 60 > $W/p1.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
