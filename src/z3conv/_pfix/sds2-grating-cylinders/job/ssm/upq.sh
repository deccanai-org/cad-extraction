#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet gr4b/1504_EQUADOR_f90185.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4b/1504_EQUADOR_f90185.json
aws s3 cp --quiet gr4b/PSU_BNR_JOB_mallesh_4e9908.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4b/PSU_BNR_JOB_mallesh_4e9908.json
aws s3 cp --quiet gr4b/One_Light_Tower_JOB_-Model_700bd1.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4b/One_Light_Tower_JOB_-Model_700bd1.json
echo ok
