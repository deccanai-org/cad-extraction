W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/probe_atr.py stage/probe_atr.py
timeout 60 $W/env/bin/python stage/probe_atr.py $W/base54/sds2-step-pipeline/decode $W/jobs/SLC5_DATABANK_JOB_f0c2c8 3932 2>&1 | tail -12
