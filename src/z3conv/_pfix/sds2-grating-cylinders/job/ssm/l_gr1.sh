#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/run_gr1.sh .
setsid nohup bash run_gr1.sh > $WD/run_gr1.out 2>&1 < /dev/null &
echo launched $!
