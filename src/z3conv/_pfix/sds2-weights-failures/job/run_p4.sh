#!/bin/bash
# re-run the analysis with the patched decode (p4) on a job list
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/p4.tgz $W/p4.tgz
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/wdump.py $W/wdump.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_p4.txt $W/ids_p4.txt
rm -rf $W/p4 && mkdir -p $W/p4 && tar xzf $W/p4.tgz -C $W/p4
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py p4 $W/ids_p4.txt ana:$W/p4/sds2-step-pipeline/decode 5 60 > $W/p4.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
