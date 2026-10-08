#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/run_gr4.sh .
: > logs/gr4.log
timeout 1300 bash run_gr4.sh 2>&1 | tail -20
