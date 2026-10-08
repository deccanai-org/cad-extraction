#!/bin/bash
# re-run the analysis with the patched decode (p3) on a job list
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/p3.tgz $W/p3.tgz
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/wdump.py $W/wdump.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_p3.txt $W/ids_p3.txt
rm -rf $W/p3 && mkdir -p $W/p3 && tar xzf $W/p3.tgz -C $W/p3
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py p3 $W/ids_p3.txt ana:$W/p3/sds2-step-pipeline/decode 4 50 > $W/p3.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
