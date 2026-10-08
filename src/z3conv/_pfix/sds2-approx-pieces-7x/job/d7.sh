#!/bin/bash
# d7: diag of the cand6 decoder (v5.5.3 + approx-pieces patch with bridge-aware loops) on every fetched job
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d7.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1
bash $W/mkvar553.sh cand6 cand6_brep.py:brep.py cand6_to_step2.py:to_step2.py
cat dirs_all.txt dirs_extra.txt > dirs_d7.txt
ls -d $W/jobs/MILL_OFFICE_JOB_BACKUP_1a696f $W/jobs/STOCKTON_REHAB_HOSPITAL_JOB_c1873a $W/jobs/689-18_Parkview_Job_884c5c >> dirs_d7.txt
VARIANTS="cand6" DIRS=dirs_d7.txt NP=${NP:-10} bash $W/diag_all.sh d7
aws s3 cp --quiet $W/d7.log $R/d7.log
