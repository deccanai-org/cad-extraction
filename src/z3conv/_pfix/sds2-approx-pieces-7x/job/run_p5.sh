W=/work/agentwork/sds2-approx-pieces-7x
cd $W; aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/p5.py $W/p5.py
timeout 60 $W/env/bin/python $W/p5.py $W/cand6/sds2-step-pipeline/decode $W/jobs/19-519_CMS_Job_0a4016 $W/jobs/IFC_MHP_JOB_1f2578 2>&1 | head
tail -3 $W/d7.log; ls $W/diag/d7 | wc -l
