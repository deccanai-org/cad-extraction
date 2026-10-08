#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; mkdir -p $W/gtest && cd $W/gtest
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/grating_t.py grating.py
cp ../gr4.py .
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
for n in 1504_EQUADOR_f90185 DSCC_JOB_ef345b; do
 timeout 900 ../env/bin/python gr4.py ../base54/sds2-step-pipeline ../jobs/$n $n.json 2>&1 | grep -v LD_PRE | tail -1 | cut -c1-500 &
done; wait
