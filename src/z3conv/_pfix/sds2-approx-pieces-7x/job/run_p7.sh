W=/work/agentwork/sds2-approx-pieces-7x
cd $W; aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/p7.py $W/p7.py
timeout 60 $W/env/bin/python $W/p7.py $W/cand9/sds2-step-pipeline/decode $W/jobs/BG_Residental_tower_Job_5d5002 4040 2>&1 | tail -40
