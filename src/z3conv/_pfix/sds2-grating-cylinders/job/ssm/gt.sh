#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; mkdir -p $W/gtest && cd $W/gtest
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/gtime.py .
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
timeout 1500 ../env/bin/python gtime.py ../v55/sds2-step-pipeline ../jobs/FMI_SAFFORD_SULFUR_TANK_JOB_948ebd 2>&1 | grep -v LD_PRE > fmi_time.txt
cat fmi_time.txt
