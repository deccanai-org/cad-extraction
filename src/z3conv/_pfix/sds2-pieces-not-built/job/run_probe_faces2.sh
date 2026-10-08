W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_faces2.py stage/probe_faces2.py
P="$W/env/bin/python stage/probe_faces2.py $W/base54/sds2-step-pipeline/decode"
timeout 60 $P $W/jobs/SLC5_DATABANK_JOB_f0c2c8 3932 2>&1 | head -20
timeout 60 $P $W/jobs/PRUDENTIAL_JOB_c5625e 15815 2>&1 | head -20
