#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
for f in v55sgc.tgz conv.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/$f .; done
rm -rf v55; mkdir -p v55 && tar xzf v55sgc.tgz -C v55
ls base54/sds2-step-pipeline/decode/sds2_to_step.py v55/sds2-step-pipeline/decode/grating.py
setsid nohup bash conv.sh v55 $W/jobs/One_Light_Tower_JOB_-Model_700bd1 > /dev/null 2>&1 < /dev/null &
setsid nohup bash conv.sh v55 $W/jobs/SHERIFFS_OFFICE_JOB_e730aa > /dev/null 2>&1 < /dev/null &
echo launched
