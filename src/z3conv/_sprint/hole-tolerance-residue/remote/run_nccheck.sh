#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$S/nc_check.py .
timeout 110 /opt/conv/env/bin/python nc_check.py nc_find.json nc_check.json 2>&1 | tail -20
aws s3 cp --quiet nc_check.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S/nc_check.json
ls census/kit_i/*.json | wc -l; tail -2 census.log
