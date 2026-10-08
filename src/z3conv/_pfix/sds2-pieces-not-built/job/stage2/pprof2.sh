W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/prof_ref2.py $W/stage/prof_ref2.py
timeout 600 $W/env/bin/python $W/stage/prof_ref2.py $W/trees/v553s/decode $W/jobs/State_Reno_df6dfb $W/ab553/v553r/State_Reno_df6dfb/State_Reno_df6dfb_stage2_skipped.csv 300 2>&1 | tail -4
