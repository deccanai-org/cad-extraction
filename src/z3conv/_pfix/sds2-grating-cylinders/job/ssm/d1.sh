#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/dump1.py .
env/bin/python dump1.py base54/sds2-step-pipeline jobs/SUSQUEHANNOCK_HS_JOB_87316d 13511 2>&1 | grep -v LD_PRE | head -70
