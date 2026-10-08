#!/bin/bash
# runs on BOX-B under setsid; census of nominal-hole causes with the deployed kit (code i)
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S
mkdir -p kit_i
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_i/ --exclude '*' --include '*.py' --include '*.json' --exclude '*/*'
grep -n "^CODE" kit_i/worker.py
md5sum kit_i/db1bolts.py kit_i/db1step.py
/opt/conv/env/bin/python runjob.py models.json kit_i census 16 > census.log 2>&1
aws s3 cp --quiet census.log $OUT/census.log
