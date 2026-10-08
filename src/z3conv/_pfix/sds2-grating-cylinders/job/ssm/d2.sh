#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/diag2.py .
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
timeout 300 env/bin/python diag2.py v55/sds2-step-pipeline jobs/SUSQUEHANNOCK_HS_JOB_87316d 13511 2>&1 | grep -v LD_PRE | tail -12
