W=/work/agentwork/sds2-approx-pieces-7x
cd $W; aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/p6.py $W/p6.py
timeout 100 $W/env/bin/python $W/p6.py $W/cand8/sds2-step-pipeline/decode $W/jobs/IFC_MHP_JOB_1f2578 697,698,700 2>&1 | tail -5
timeout 100 $W/env/bin/python $W/p6.py $W/cand8/sds2-step-pipeline/decode $W/jobs/19-519_CMS_Job_0a4016 7822,9077 2>&1 | tail -3
