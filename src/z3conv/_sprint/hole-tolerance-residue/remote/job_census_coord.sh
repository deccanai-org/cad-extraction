#!/bin/bash
S=hole-tolerance-residue; W=/work/agentwork/$S; cd $W
export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export HTR_PY=$W/conv/env/bin/python HTR_ASC=1
$HTR_PY runjob2.py models2.json kit_jg,kit_jp census 16 > census_coord.log 2>&1
aws s3 cp --quiet census_coord.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$S/census_coord.log
