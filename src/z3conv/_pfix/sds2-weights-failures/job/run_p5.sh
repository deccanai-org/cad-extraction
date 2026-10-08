#!/bin/bash
# re-run the analysis with the patched decode (p5) on a job list
W=/work/agentwork/sds2-weights-failures; cd $W
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/p5.tgz $W/p5.tgz
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/wdump.py $W/wdump.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ids_p5.txt $W/ids_p5.txt
rm -rf $W/p5 && mkdir -p $W/p5 && tar xzf $W/p5.tgz -C $W/p5
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana.py p5 $W/ids_p5.txt ana:$W/p5/sds2-step-pipeline/decode 8 90 > $W/p5.out 2>&1" > /dev/null 2>&1 < /dev/null &
echo started
