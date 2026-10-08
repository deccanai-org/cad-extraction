#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; mkdir -p $W/gtest2 && cd $W/gtest2
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/grating_u.py grating.py
cp ../gtest/gtime.py .
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
for s in 1141 1492 1635; do timeout 200 ../env/bin/python gtime.py ../v55/sds2-step-pipeline ../jobs/1504_EQUADOR_f90185 $s 2>&1 | grep -v LD_PRE | tail -1; done
for s in 4644 4701; do timeout 200 ../env/bin/python gtime.py ../v55/sds2-step-pipeline ../jobs/DSCC_JOB_ef345b $s 2>&1 | grep -v LD_PRE | tail -1; done
