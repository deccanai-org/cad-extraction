#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; mkdir -p $W/gtest3 && cd $W/gtest3
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/grating_f.py grating.py
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/fbench.py .
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
J=../jobs/FMI_SAFFORD_SULFUR_TANK_JOB_948ebd
for v in base nofuzzy nofuzzy_obb nofuzzy_obb_nounify fuzzy_obb_nounify; do
  timeout 200 ../env/bin/python fbench.py ../v55/sds2-step-pipeline $J 869 $v 2>&1 | grep -v LD_PRE | tail -1 &
done; wait
for v in base nofuzzy_obb_nounify; do
  timeout 300 ../env/bin/python fbench.py ../v55/sds2-step-pipeline $J 872 $v 2>&1 | grep -v LD_PRE | tail -1 &
done; wait
