#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/pipe1.py .
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
mkdir -p pipe1
for n in PSU_BNR_JOB_mallesh_4e9908 SOCORRO_ISD_JOB_8566ee void_4d54fd THERMOFISHER_JOB_bff8f8; do
 timeout 500 env/bin/python pipe1.py base54/sds2-step-pipeline jobs/$n pipe1/$n.json 2>&1 | grep -v LD_PRE | tail -2 &
done; wait
aws s3 cp --recursive --quiet pipe1 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/pipe1/
