#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/render.py .
export MPLBACKEND=Agg LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
mkdir -p img
P=$W/v55/sds2-step-pipeline
timeout 300 env/bin/python render.py $P jobs/SHERIFFS_OFFICE_JOB_e730aa img/sheriffs_grating.png g:3397 2>&1 | grep -v LD_PRE | tail -3
timeout 300 env/bin/python render.py $P jobs/PSU_BNR_JOB_mallesh_4e9908 img/psu_tread.png g:2997 2>&1 | grep -v LD_PRE | tail -3
timeout 300 env/bin/python render.py $P jobs/DSCC_JOB_ef345b img/dscc_rod.png r:3564 2>&1 | grep -v LD_PRE | tail -3
timeout 300 env/bin/python render.py $P jobs/One_Light_Tower_JOB_-Model_700bd1 img/olt_tread.png g:1508 2>&1 | grep -v LD_PRE | tail -3
aws s3 cp --recursive --quiet img s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/img/
